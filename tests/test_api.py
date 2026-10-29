"""API (`web/api.py`) testlari: autentifikatsiya, javob yuborish, natijalar.

Ishga tushirish:
    python tests/test_api.py

Tarmoqqa chiqilmaydi: `aiohttp.test_utils` yordamida ilova xotirada ko'tariladi
va so'rovlar shu ilovaga yuboriladi. Telegram tokeni kerak emas — test o'zi
sun'iy `initData` imzolaydi.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_service, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AATestTokenForApiChecks"
USER = {
    "id": 909_111_222,
    "first_name": "Sardor",
    "last_name": "Toshmatov",
    "username": "sardor",
}
QUESTIONS = 5
KEY = "1A2B3C4D5A"
DIFFICULTIES = [-1.0, -0.5, 0.0, 0.5, 1.0]

# Server `config.BOT_TOKEN` bilan tekshiradi — testda o'zimiznikini qo'yamiz.
config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False


def build_init_data(user: dict, *, token: str = TOKEN, age: int = 0) -> str:
    """Imzolangan `initData` satrini yasaydi (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAF-test-query",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, token)
    return urlencode(payload)


VALID_HEADERS = {"X-Init-Data": build_init_data(USER)}


async def make_exam(
    repos: Repositories,
    *,
    code: str,
    title: str,
    start_offset: float,
    end_offset: float,
    result_offset: float,
    total: int = QUESTIONS,
    key: str = KEY,
    difficulties: list[float] | None = None,
) -> int:
    """Hozirgi vaqtga nisbatan siljitilgan vaqtlar bilan imtihon yaratadi."""
    now = exam_service.utc_now()
    return await repos.exams.create(
        title=title,
        test_code=code,
        start_time=exam_service.to_db_time(now + timedelta(minutes=start_offset)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=end_offset)),
        result_time=exam_service.to_db_time(now + timedelta(minutes=result_offset)),
        total_questions=total,
        answer_key=key,
        difficulty_logits=exam_service.difficulties_to_json(
            difficulties if difficulties is not None else [0.0] * total
        ),
        created_by=1,
    )


async def check_auth(client: TestClient) -> None:
    """Autentifikatsiya qoidalari."""
    response = await client.get("/api/health")
    assert response.status == 200, response.status
    print("[OK] /api/health autentifikatsiyasiz ishlaydi")

    response = await client.get("/api/me")
    assert response.status == 401, response.status
    print(f"[OK] initData'siz so'rov rad etildi: {(await response.json())['error']}")

    response = await client.get(
        "/api/me", headers={"X-Init-Data": build_init_data(USER, token="999:WRONG")}
    )
    assert response.status == 401, response.status
    print("[OK] Noto'g'ri imzo rad etildi")

    response = await client.get(
        "/api/me", headers={"X-Init-Data": build_init_data(USER, age=config.INITDATA_MAX_AGE + 60)}
    )
    assert response.status == 401, response.status
    print("[OK] Muddati o'tgan initData rad etildi")

    response = await client.get("/api/me", headers=VALID_HEADERS)
    payload = await response.json()
    assert response.status == 200 and payload["full_name"] == "Sardor Toshmatov", payload
    assert payload["tests_done"] == 0 and payload["user_id"] == USER["id"]
    print(f"[OK] To'g'ri so'rov qabul qilindi: {payload['full_name']} (ID {payload['user_id']})")


async def check_profile(client: TestClient) -> None:
    """Profilni o'qish va tahrirlash."""
    response = await client.post("/api/me", headers=VALID_HEADERS, json={"full_name": "Sa"})
    assert response.status == 400, response.status
    print(f"[OK] Qisqa ism rad etildi: {(await response.json())['error']}")

    response = await client.post(
        "/api/me", headers=VALID_HEADERS, json={"full_name": "Sardor   Toshmatov  o'g'li"}
    )
    payload = await response.json()
    assert response.status == 200, payload
    assert payload["full_name"] == "Sardor Toshmatov o'g'li", payload
    print(f"[OK] Profil yangilandi (ortiqcha bo'shliqlar tozalandi): {payload['full_name']}")

    response = await client.get("/api/me", headers=VALID_HEADERS)
    payload = await response.json()
    assert payload["full_name"] == "Sardor Toshmatov o'g'li"
    print("[OK] Yangilangan ism bazadan o'qildi")


async def check_exam_flow(client: TestClient, active_exam_id: int, upcoming_exam_id: int) -> None:
    """Kodni tekshirish, javob yuborish va cheklovlar."""
    response = await client.get("/api/exams", headers=VALID_HEADERS)
    payload = await response.json()
    assert response.status == 200, payload

    exams = {item["exam_id"]: item for item in payload["exams"]}
    assert active_exam_id in exams and upcoming_exam_id in exams, list(exams)
    active = exams[active_exam_id]
    assert active["status"] == "active" and active["can_submit"] is True
    assert active["submitted"] is False and active["total_questions"] == QUESTIONS
    assert active["average_difficulty"] is not None
    print(
        f"[OK] «Navbat» ro'yxati: {len(exams)} ta imtihon, faol imtihon "
        f"{active['seconds_left']} sekunddan keyin yopiladi"
    )

    raw = await response.text()
    assert KEY not in raw and "answer_key" not in raw and "difficulty_logits" not in raw
    print("[OK] Javoblar kaliti va logitlar API javobida oshkor bo'lmadi")

    response = await client.post(
        "/api/verify-code", headers=VALID_HEADERS, json={"test_code": "YOQ123"}
    )
    assert response.status == 404, response.status
    print(f"[OK] Noto'g'ri kod rad etildi: {(await response.json())['error']}")

    response = await client.post("/api/verify-code", headers=VALID_HEADERS, json={"test_code": "ab"})
    assert response.status == 400, response.status
    print("[OK] Juda qisqa kod rad etildi")

    response = await client.post(
        "/api/verify-code", headers=VALID_HEADERS, json={"test_code": " exam01 "}
    )
    payload = await response.json()
    assert response.status == 200 and payload["can_submit"] is True, payload
    assert payload["title"] == "Faol imtihon" and "answer_key" not in json.dumps(payload)
    print(f"[OK] Kod tasdiqlandi: «{payload['title']}», {payload['total_questions']} savol")

    response = await client.post(
        "/api/verify-code", headers=VALID_HEADERS, json={"test_code": "EXAM02"}
    )
    payload = await response.json()
    assert response.status == 200 and payload["can_submit"] is False, payload
    print(f"[OK] Kutilayotgan imtihon uchun kod rad etildi: {payload['message']}")

    response = await client.post(
        "/api/submit", headers=VALID_HEADERS, json={"test_code": "EXAM01", "answers": "   "}
    )
    assert response.status == 400, response.status
    print(f"[OK] Bo'sh javoblar rad etildi: {(await response.json())['error']}")

    response = await client.post(
        "/api/submit", headers=VALID_HEADERS, json={"test_code": "exam01", "answers": "1A2B3X"}
    )
    payload = await response.json()
    assert response.status == 200 and payload["ok"] is True, payload
    assert payload["answered"] == 2, payload
    print(f"[OK] Javob qabul qilindi: {payload['message']}")

    response = await client.post(
        "/api/submit",
        headers=VALID_HEADERS,
        json={"test_code": "EXAM01", "answers": "1A2B3C4D5A"},
    )
    assert response.status == 409, response.status
    print(f"[OK] Takroriy yuborish rad etildi: {(await response.json())['error']}")

    response = await client.post(
        "/api/submit", headers=VALID_HEADERS, json={"test_code": "EXAM02", "answers": "1A2B3"}
    )
    assert response.status == 403, response.status
    print(f"[OK] Muddatdan oldin yuborish rad etildi: {(await response.json())['error']}")

    response = await client.get("/api/results", headers=VALID_HEADERS)
    payload = await response.json()
    assert payload["published"] == [] and len(payload["pending"]) == 1, payload
    assert payload["summary"]["attempts"] == 1
    pending = payload["pending"][0]
    # Web App countdown'i uchun aniq (UTC ISO) natija vaqti ham beriladi.
    assert pending["result_time"], pending
    print(f"[OK] Natija hali yopiq: «{pending['title']}» (e'lon: {pending['result_time_local']})")


async def check_published_results(repos: Repositories, client: TestClient, exam_id: int) -> None:
    """Natija vaqti kelgach natijaning ochilishi va batafsil hisobot."""
    now = exam_service.utc_now()
    await repos.exams.update_times(
        exam_id,
        end_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        result_time=exam_service.to_db_time(now - timedelta(minutes=5)),
    )

    response = await client.get(f"/api/results/{exam_id}", headers=VALID_HEADERS)
    payload = await response.json()
    assert response.status == 200, payload
    assert payload["total_questions"] == QUESTIONS and len(payload["items"]) == QUESTIONS
    assert payload["raw_score"] == 2, payload["raw_score"]
    assert payload["items"][2]["given_answer"] is None
    assert payload["items"][2]["is_correct"] is False
    assert payload["items"][0]["correct_answer"] == "A" and payload["items"][0]["is_correct"] is True
    assert payload["theta"] is not None and payload["theta_interval"] is not None
    # Asosiy foydalanuvchi ko'rsatkichi — sertifikat bali va uning intervali.
    assert payload["scaled_score"] is not None, payload
    assert payload["scaled_interval"] is not None, payload
    assert set(payload["subject_balls"]) == {"algebra", "geometry"}, payload
    print(
        f"[OK] Batafsil hisobot: {payload['raw_score']}/{QUESTIONS} → "
        f"ball = {payload['scaled_score']:.2f}, "
        f"interval = {payload['scaled_interval']} ({payload['ability_level']})"
    )

    # Natijalar ro'yxati va diagramma sertifikat bali bo'yicha quriladi.
    listed = await (await client.get("/api/results", headers=VALID_HEADERS)).json()
    entry = [row for row in listed["published"] if row["exam_id"] == exam_id][0]
    assert entry["scaled_score"] is not None, entry
    assert entry["level"], entry
    assert listed["chart"]["score"], listed["chart"]
    assert listed["summary"]["best_score"] is not None, listed["summary"]
    assert listed["summary"]["average_score"] is not None, listed["summary"]
    print(
        f"[OK] Natijalar ro'yxati: ball = {entry['scaled_score']:.2f}, "
        f"diagramma score[] va best/average score to'ldi"
    )

    exam = await repos.exams.get(exam_id)
    assert exam is not None and exam.is_graded
    print("[OK] Natija so'ralganda avtomatik baholandi (fon vazifasi zaxirasi)")

    response = await client.get("/api/results", headers=VALID_HEADERS)
    payload = await response.json()
    assert len(payload["published"]) == 1 and payload["pending"] == [], payload
    published = payload["published"][0]
    assert payload["chart"]["theta"] == [published["theta"]]
    assert "scaled" not in payload["chart"], payload["chart"]
    assert payload["summary"]["best_theta"] == published["theta"]
    assert "best_scaled" not in payload["summary"], payload["summary"]
    # Daraja (NC … A+) ro'yxatda ham keladi — Web App chipi shu maydondan oladi.
    assert published["level"] in {"NC", "C", "C+", "B", "B+", "A", "A+"}, published
    assert published["result_time"], published
    print(
        f"[OK] Grafik/tarix: {payload['chart']['labels']} → {payload['chart']['theta']} logit "
        f"(o'rtacha {payload['summary']['average_theta']})"
    )

    # Boshqa o'quvchi qatnashmagan imtihonni so'rasa — 404
    other = build_init_data({"id": 909_111_999, "first_name": "Boshqa"})
    response = await client.get(f"/api/results/{exam_id}", headers={"X-Init-Data": other})
    assert response.status == 404, response.status
    print(f"[OK] Qatnashmagan imtihon uchun 404: {(await response.json())['error']}")

    # Kalit faqat natija e'lon qilingandan keyin ko'rinadi (bu rejalashtirilgan)
    response = await client.get(f"/api/results/{exam_id}", headers=VALID_HEADERS)
    assert (await response.json())["items"][3]["correct_answer"] == "D"
    print("[OK] E'lon qilingandan keyin savollar kaliti hisobotda ko'rinadi")


async def check_static(client: TestClient) -> None:
    """Mini App sahifasi, statik fayllar va offline bo'limi."""
    response = await client.get("/")
    body = await response.text()
    assert response.status == 200 and "bottom-nav" in body and "Navbat" in body
    print("[OK] Mini App sahifasi (index.html) berildi — 4 tabli navigatsiya joyida")

    for asset in (
        "/static/css/style.css",
        "/static/js/api.js",
        "/static/js/queue.js",
        "/static/js/results.js",
        "/static/js/profile.js",
        "/static/js/offline.js",
        "/static/js/app.js",
    ):
        response = await client.get(asset)
        assert response.status == 200, asset
    print("[OK] Barcha statik fayllar (/static/*) mavjud")

    response = await client.get("/api/offline", headers=VALID_HEADERS)
    payload = await response.json()
    assert response.status == 200 and len(payload["regions"]) >= 10, payload
    print(f"[OK] Offline bo'limi: {len(payload['regions'])} ta hudud (statik ro'yxat)")


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_api_"))
    db = Database(tmp_dir / "api_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("API testlari (aiohttp test client — tarmoqqa chiqilmaydi)")
    print("=" * 72)
    try:
        active_id = await make_exam(
            repos,
            code="exam01",
            title="Faol imtihon",
            start_offset=-10,
            end_offset=+50,
            result_offset=+120,
            difficulties=DIFFICULTIES,
        )
        upcoming_id = await make_exam(
            repos,
            code="exam02",
            title="Kutilayotgan imtihon",
            start_offset=+60,
            end_offset=+120,
            result_offset=+180,
            total=3,
            key="1A2B3C",
            difficulties=[0.0, 0.5, -0.5],
        )

        app = create_app(repos)
        async with TestClient(TestServer(app)) as client:
            await check_auth(client)
            await check_profile(client)
            await check_exam_flow(client, active_id, upcoming_id)
            await check_published_results(repos, client, active_id)
            await check_static(client)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha API tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
