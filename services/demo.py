"""Sinov (demo) testi — o'quvchi javob oynasini **kod kiritmasdan** sinash uchun.

`DEMO_MODE=1` bo'lganda bot ishga tushganda `SINOV` kodli test **avtomatik**
yaratiladi (agar yo'q bo'lsa). Foydalanuvchi shunchaki `SINOV` kodini kiritadi
va javob varaqasini darhol sinab ko'radi.

Bot to'liq tayyor bo'lgach: `.env` da `DEMO_MODE=0` qilish kifoya.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from database.models import User
from database.repository import Repositories
from services import exam_admin, exam_service

logger = logging.getLogger(__name__)

#: Sinov testi kodi va sarlavhasi.
DEMO_CODE: str = "SINOV3"
DEMO_TITLE: str = "🧪 Sinov testi (javob oynasini sinash)"
DEMO_TOTAL: int = 45


def demo_answer_key(total: int = DEMO_TOTAL) -> str:
    """Sinov kaliti: 1–35 variantlar + **36a…45b qismli** sonli javoblar.

    Qismli blok (`|36a:36,36b:37,…`) — shu sababli 36–45 savollar **a/b**
    qismlariga bo'linadi va har biri **alohida** savol bo'ladi (o'z `b` si bilan).
    """
    letters = "".join(
        f"{position}{'ABCD'[(position - 1) % 4]}" for position in range(1, 36)
    )
    parts = ",".join(
        f"{position}{part}:{_demo_value(position, part)}"
        for position in range(36, 46)
        for part in ("a", "b")
    )
    return f"{letters}|{parts}"


def _demo_value(position: int, part: str) -> str:
    """Sinov uchun oddiy sonli javob (`a` → pozitsiya, `b` → pozitsiya + 1)."""
    return str(position if part == "a" else position + 1)


async def _purge_demo(repos: Repositories) -> None:
    """Sinov testining **barcha** yozuvlarini o'chiradi: sessiya → forma → imtihon.

    Tartib FK uchun muhim. `exams` yo'q bo'lsa ham forma qolgan bo'lishi mumkin
    (qoldiq) — shu sababli hammasi **kod bo'yicha** o'chiriladi. Best-effort:
    xato bo'lsa log yoziladi, bot to'xtamaydi.
    """
    conn = repos.db.connection
    try:
        await conn.execute(
            "DELETE FROM exam_sessions WHERE form_id IN "
            "(SELECT form_id FROM forms WHERE test_code = ?)",
            (DEMO_CODE,),
        )
        await conn.execute("DELETE FROM forms WHERE test_code = ?", (DEMO_CODE,))
        await conn.execute("DELETE FROM exams WHERE test_code = ?", (DEMO_CODE,))
        await conn.commit()
    except Exception:
        await conn.rollback()
        logger.exception("Sinov testining qoldiq yozuvlarini tozalab bo'lmadi")


async def ensure_demo_exam(repos: Repositories, created_by: int = 0) -> int | None:
    """`SINOV` kodli sinov testini yaratadi (mavjud bo'lsa — tegmaydi).

    Args:
        created_by: imtihon muallifi (`forms.created_by` → `users` FK).
            Bazada bo'lmasa — shu yerda yaratiladi.

    Qaytaradi: `exam_id` yoki yaratib bo'lmasa `None`.
    """
    existing = await repos.exams.get_by_code(DEMO_CODE)
    if existing is not None and "|" in (existing.answer_key or ""):
        return existing.exam_id
    if existing is not None:
        # Eski formatdagi sinov testi — qayta yaratiladi.
        logger.info("Sinov testi qayta yaratiladi (eski yozuvlar tozalanadi)")
        await _purge_demo(repos)

    # `created_by` uchun foydalanuvchi (FK talabi) — yo'q bo'lsa yaratiladi.
    await repos.users.upsert(User(user_id=int(created_by), full_name="🧪 Sinov (tizim)"))

    now = exam_service.utc_now()
    try:
        created = await exam_admin.create_exam(
            repos,
            title=DEMO_TITLE,
            test_code=DEMO_CODE,
            total_questions=DEMO_TOTAL,
            answer_key=demo_answer_key(),
            # Qiyinchilik kiritilmaydi — keyin javoblar bo'yicha avtomatik tekislanadi.
            difficulty=None,
            start_time=exam_service.to_db_time(now - timedelta(hours=1)),
            end_time=exam_service.to_db_time(now + timedelta(days=30)),
            result_time=exam_service.to_db_time(now + timedelta(days=30, hours=1)),
            created_by=created_by,
        )
    except Exception:  # sinov testi muhim emas — botni to'xtatmaymiz
        logger.exception("Sinov testini yaratib bo'lmadi")
        return None

    logger.info(
        "🧪 Sinov testi yaratildi: kod=%s, exam_id=%s, savollar=%d",
        DEMO_CODE,
        created.exam_id,
        created.total_questions,
    )
    return created.exam_id
