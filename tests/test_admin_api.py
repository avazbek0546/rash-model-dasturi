"""Admin Web App API'si: `/api/v2/me` + `/api/v2/admin/*` (Telegram'siz).

Tekshiriladi:
    1. `/api/v2/me` admin va oddiy o'quvchi uchun `is_admin` ni to'g'ri beradi;
    2. admin endpoint'lari oddiy o'quvchini **403** bilan rad etadi;
    3. admin test yarata oladi (`exams` + `exam_sessions`);
    4. noto'g'ri kalitda **400** va qisman yozuv qolmaydi;
    5. ro'yxat (`GET /api/v2/admin/exams`) yaratilgan testni ko'rsatadi.

Ishga tushirish:
    python tests/test_admin_api.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AAAdminApiChecks"
ADMIN = {"id": 707_000_001, "first_name": "Olim", "last_name": "Ustoz"}
STUDENT = {"id": 707_000_002, "first_name": "Ali", "last_name": "Valiyev"}

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN["id"]
config.ADMIN_IDS = frozenset({ADMIN["id"]})


def init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-admin",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


ADMIN_HEADERS = {"X-Init-Data": init_data(ADMIN)}
STUDENT_HEADERS = {"X-Init-Data": init_data(STUDENT)}

VALID_BODY = {
    "title": "Web admin testi",
    "test_code": "WEBA01",
    "total_questions": 3,
    "answer_key": "1A2B3C",
    "difficulty": "90, 75, 50",
    "start_time": "15.01.2027 09:00",
    "end_time": "15.01.2027 10:30",
    "result_time": "15.01.2027 12:00",
}


async def run_checks(repos: Repositories) -> None:
    """Sxemani bir marta ochib, barcha endpoint'larni tekshiradi."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        # 1) /me — admin va oddiy o'quvchi
        admin_me = await (await client.get("/api/v2/me", headers=ADMIN_HEADERS)).json()
        assert admin_me["is_admin"] is True, admin_me
        student_me = await (
            await client.get("/api/v2/me", headers=STUDENT_HEADERS)
        ).json()
        assert student_me["is_admin"] is False, student_me
        print("[OK] /api/v2/me: admin=True, o'quvchi=False")

        # 2) Oddiy o'quvchi admin endpoint'lariga kira olmaydi
        denied_list = await client.get("/api/v2/admin/exams", headers=STUDENT_HEADERS)
        assert denied_list.status == 403, denied_list.status
        denied_create = await client.post(
            "/api/v2/admin/exams", json=VALID_BODY, headers=STUDENT_HEADERS
        )
        assert denied_create.status == 403, denied_create.status
        print("[OK] Admin endpoint'lari oddiy o'quvchini 403 bilan rad etdi")

        # 3) Admin test yaratadi
        created = await client.post(
            "/api/v2/admin/exams", json=VALID_BODY, headers=ADMIN_HEADERS
        )
        assert created.status == 200, (created.status, await created.text())
        payload = await created.json()
        assert payload["ok"] and payload["test_code"] == "WEBA01", payload

        exam = await repos.exams.get_by_code("WEBA01")
        assert exam is not None and exam.total_questions == 3, exam
        assert exam.difficulties[0] < -2.0, exam.difficulties  # 90% → -2.197
        session = await repos.sessions.get_by_test_code("WEBA01")
        assert session is not None, "exam_sessions yaratilmadi"
        print("[OK] POST /admin/exams: imtihon + sessiya yaratildi (WEBA01)")

        # 4) Noto'g'ri kalit → 400 va qisman yozuv bo'lmasin
        bad_body = dict(VALID_BODY, test_code="WEBA02", answer_key="1A")
        bad = await client.post(
            "/api/v2/admin/exams", json=bad_body, headers=ADMIN_HEADERS
        )
        assert bad.status == 400, (bad.status, await bad.text())
        assert await repos.exams.get_by_code("WEBA02") is None, "qisman yozuv qoldi"
        print("[OK] Noto'g'ri kalit → 400, qisman yozuv qolmadi")

        # 5) Ro'yxat
        listed = await (
            await client.get("/api/v2/admin/exams", headers=ADMIN_HEADERS)
        ).json()
        assert any(row["test_code"] == "WEBA01" for row in listed["exams"]), listed
        assert listed["exams"][0]["status_title"], listed["exams"][0]
        assert listed["exams"][0]["solutions_total"] == 3, listed["exams"][0]
        assert listed["exams"][0]["solutions_covered"] == 0, listed["exams"][0]
        print("[OK] GET /admin/exams: ro'yxatda WEBA01 (holat + yechim qamrovi)")

        # 6) PDF hisobot: admin havolasi + fayl (yaroqsiz token → 403)
        await repos.answers.submit(
            user_id=STUDENT["id"], exam_id=exam.exam_id, submitted_answers="1A2B3C"
        )
        denied_link = await client.post(
            f"/api/v2/admin/exams/{exam.exam_id}/report-link",
            headers=STUDENT_HEADERS,
        )
        assert denied_link.status == 403, denied_link.status

        link = await client.post(
            f"/api/v2/admin/exams/{exam.exam_id}/report-link",
            headers=ADMIN_HEADERS,
        )
        assert link.status == 200, (link.status, await link.text())
        payload = await link.json()
        url = payload["url"]
        assert "/api/v2/report/" in url, url
        token = url.rsplit("/", 1)[-1]
        assert payload["path"] == f"/api/v2/report/{token}", payload

        # Proksi (Railway/Cloudflare Tunnel) ortida `request.url.origin()`
        # doim `http://...` bo'ladi — HTTPS sahifadan bunday so'rovni brauzer
        # bloklab, PDF o'rniga "Failed to fetch" chiqarardi. Endi proksi
        # sarlavhalari hisobga olinadi, `path` esa o'z origin'ida yuklanadi.
        proxied = await client.post(
            f"/api/v2/admin/exams/{exam.exam_id}/report-link",
            headers={
                **ADMIN_HEADERS,
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "rash-model.up.railway.app",
            },
        )
        proxied_payload = await proxied.json()
        proxied_token = proxied_payload["path"].rsplit("/", 1)[-1]
        assert proxied_payload["url"] == (
            "https://rash-model.up.railway.app/api/v2/report/" + proxied_token
        ), proxied_payload
        print(f"[OK] Proksi ortida havola HTTPS: {proxied_payload['url']}")

        pdf = await client.get(f"/api/v2/report/{token}")
        assert pdf.status == 200, (pdf.status, await pdf.text())
        assert pdf.headers["Content-Type"] == "application/pdf", pdf.headers
        body = await pdf.read()
        assert body[:4] == b"%PDF", body[:8]
        assert len(body) > 5000, len(body)

        bad = await client.get("/api/v2/report/1.1.deadbeef")
        assert bad.status == 403, bad.status
        print(
            f"[OK] PDF hisobot: havola + fayl ({len(body)} bayt), "
            "yaroqsiz token 403"
        )

        # 7) «🎬 Yechimlar»: qamrov → video yechim (bot file_id) → o'chirish
        sol_url = f"/api/v2/admin/exams/{exam.exam_id}/solutions"
        denied_sol = await client.get(sol_url, headers=STUDENT_HEADERS)
        assert denied_sol.status == 403, denied_sol.status

        cov = await client.get(sol_url, headers=ADMIN_HEADERS)
        assert cov.status == 200, (cov.status, await cov.text())
        data = await cov.json()
        assert data["total"] == 3 and data["covered"] == 0, data
        assert data["missing"] == ["1", "2", "3"], data
        assert len(data["items"]) == 3 and data["items"][0]["covered"] is False
        assert "bot_username" in data, data  # bot bo'lmasa — None
        print("[OK] GET .../solutions: qamrov 0/3, yetishmayotganlar aniqlandi")

        # Faylni faqat bot yuklaydi (`file_id`), API esa uni faqat o'qiydi.
        # Shu sababli yuklashni repository orqali imitatsiya qilamiz.
        await repos.solutions.upsert(
            exam_id=exam.exam_id,
            question_number=2,
            solution_type="video",
            solution_file_id="VIDEO-FILE-ID-2",
            created_by=ADMIN["id"],
        )
        cov2 = await (await client.get(sol_url, headers=ADMIN_HEADERS)).json()
        assert cov2["covered"] == 1 and cov2["missing"] == ["1", "3"], cov2
        row2 = [row for row in cov2["items"] if row["label"] == "2"][0]
        assert row2["covered"] and row2["type"] == "video", row2
        assert row2["is_file"] is True and "text" not in row2, row2
        print("[OK] Video yechim (bot file_id): qamrov 1/3, turi=video")

        # Matnli yechim endpoint'i butunlay olib tashlangan.
        text_endpoint = await client.post(
            "/api/v2/admin/solutions/text",
            json={"exam_id": exam.exam_id, "question": 2, "text": "eski usul"},
            headers=ADMIN_HEADERS,
        )
        assert text_endpoint.status == 404, text_endpoint.status
        print("[OK] POST .../solutions/text: endpoint olib tashlangan (404)")

        denied_del = await client.post(
            "/api/v2/admin/solutions/delete",
            json={"exam_id": exam.exam_id, "question": 2},
            headers=STUDENT_HEADERS,
        )
        assert denied_del.status == 403, denied_del.status

        removed = await client.post(
            "/api/v2/admin/solutions/delete",
            json={"exam_id": exam.exam_id, "question": 2},
            headers=ADMIN_HEADERS,
        )
        assert removed.status == 200, (removed.status, await removed.text())
        cov3 = await (await client.get(sol_url, headers=ADMIN_HEADERS)).json()
        assert cov3["covered"] == 0 and cov3["missing"] == ["1", "2", "3"], cov3
        print("[OK] POST .../solutions/delete: o'chirildi (qamrov 0/3)")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="admin_api_"))
    db = Database(tmp_dir / "admin_api.db")
    await db.connect()
    repos = Repositories(db)
    await repos.users.upsert(
        User(user_id=ADMIN["id"], full_name="Olim Ustoz", username="ustoz")
    )
    await repos.users.upsert(
        User(user_id=STUDENT["id"], full_name="Ali Valiyev", username=None)
    )

    print("=" * 72)
    print("Admin Web App API testi (/api/v2/me + /api/v2/admin/*)")
    print("=" * 72)
    try:
        await run_checks(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha admin API tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
