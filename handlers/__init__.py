"""Handler'lar paketi.

Router'lar ro'yxati va ularning tartibi muhim:
    1. start          — /start, /help, reply menyu, Web App tugmasi
    2. webapp         — /app (Mini App'ni ochish)
    3. admin_exam     — /new_exam ustasi (faqat o'qituvchi)
    4. admin          — /stats, /exams (faqat o'qituvchi)
    5. admin_solution — /add_solution va video/media yechim yuklash (o'qituvchi)
    6. analysis       — «🔍 Test tahlili» bo'limi (o'quvchi)
    7. fallback       — boshqa barcha xabarlar (ENG OXIRGI bo'lishi shart)

Eski "mashq rejimi" (chatda savol-javob) arxivga o'tkazildi: `handlers/test.py`,
`handlers/results.py`, `handlers/about.py` va `services/test_session.py` fayllari
o'chirilmaydi, lekin router'ga ulanmaydi (ularning o'rnini Web App egalladi).
"""

from __future__ import annotations

from aiogram import Router

from handlers import (
    admin,
    admin_exam,
    admin_manage,
    admin_solution,
    analysis,
    fallback,
    start,
    webapp,
)

# Arxivlangan (ulanmaydigan) modullar — kelajakda kerak bo'lsa qo'shiladi.
LEGACY_MODULES: tuple[str, ...] = ("test", "results", "about")


def setup_routers() -> Router:
    """Barcha router'larni bitta ildiz router'ga (tartib bilan) ulaydi."""
    root = Router(name="root")
    for module in (
        start,
        webapp,
        admin_exam,
        admin,
        admin_manage,
        admin_solution,
        analysis,
        fallback,
    ):
        root.include_router(module.router)
    return root


__all__ = ["setup_routers", "LEGACY_MODULES"]
