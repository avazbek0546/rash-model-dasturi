"""Standart `p → b` qiyinchilik xaritasini imtihonlarga qo'llash.

Maqsad
------
`services/default_difficulty.py` dagi 55 itemli `p` foizlardan hisoblangan
`b` ni mavjud imtihonlarning `exams.difficulty_logits` maydoniga yozadi.
Shundan keyin baholash (va regrade) har bir item uchun o'z `b` siga ega
bo'ladi.

Ishlatish::

    # Dry-run (hech narsa yozilmaydi) — barcha imtihonlar ro'yxati
    python scripts/apply_default_difficulty.py

    # Bitta imtihon uchun
    python scripts/apply_default_difficulty.py --exam-id 12 --apply

    # Test kodi bo'yicha
    python scripts/apply_default_difficulty.py --test-code MATH2025 --apply

    # Yozgandan keyin darhol qayta baholash
    python scripts/apply_default_difficulty.py --exam-id 12 --apply --regrade

Xavfsizlik: standart rejim — **dry-run**. Yozish uchun `--apply` bering.
`--regrade` faqat `--apply` bilan birga ishlaydi.

Diqqat: `--apply` imtihondagi mavjud per-item `b` (masalan JMLE bank) ni ham
standart xarita bilan **almashtiradi**. Aniq kalibrlangan bankni saqlab
qolmoqchi bo'lsangiz, `--exam-id` yoki `--test-code` bilan faqat kerakli
imtihonni tanlang.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import default_difficulty, exam_service, grading  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standart p → b xaritasini imtihonlarga qo'llash"
    )
    parser.add_argument("--exam-id", type=int, default=0, help="Bitta imtihon ID")
    parser.add_argument("--test-code", default="", help="Test kodi bo'yicha filtr")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Haqiqatan yozish (berilmasa — faqat dry-run)",
    )
    parser.add_argument(
        "--regrade",
        action="store_true",
        help="Yozgandan keyin imtihonlarni qayta baholash (--apply kerak)",
    )
    return parser


async def _select_exams(repos: Repositories, args: argparse.Namespace) -> list:
    """Filtr bo'yicha imtihonlarni tanlaydi."""
    if args.exam_id:
        exam = await repos.exams.get(int(args.exam_id))
        return [exam] if exam is not None else []
    if args.test_code:
        exam = await repos.exams.get_by_code(str(args.test_code))
        return [exam] if exam is not None else []
    return await repos.exams.list_all(limit=100000)


async def _main(args: argparse.Namespace) -> int:
    if args.regrade and not args.apply:
        print("`--regrade` faqat `--apply` bilan ishlaydi.")
        return 2

    default_json = default_difficulty.default_difficulty_json()
    preview = default_difficulty.default_b_by_key()
    print(f"Standart xarita: {len(default_difficulty.DEFAULT_B_BY_LABEL)} item")
    print(
        "b oralig'i: "
        f"{min(preview.values()):+.3f} … {max(preview.values()):+.3f}"
    )
    print(f"JSON (birinchi 160 belgi): {default_json[:160]}…")

    db = Database(config.DB_PATH)
    await db.connect()
    try:
        repos = Repositories(db)
        exams = await _select_exams(repos, args)
        if not exams:
            print("Imtihon topilmadi.")
            return 2

        for exam in exams:
            print(
                f"\nExam #{exam.exam_id} [{exam.test_code}] {exam.title} "
                f"— {exam.total_questions} pozitsiya"
            )
            current = str(exam.difficulty_logits or "").strip()
            if current == default_json:
                print("  allaqachon standart xarita.")
                continue
            if not args.apply:
                print("  DRY-RUN: yozilmadi (yozish uchun --apply).")
                continue

            await repos.exams.update_difficulty_logits(exam.exam_id, default_json)
            print("  OK: standart xarita yozildi.")
            if args.regrade:
                graded = await grading.grade_exam(repos, exam, regrade=True)
                print(f"  REGRADE: {graded} javob qayta baholandi.")

        if not args.apply:
            print("\nDRY-RUN: hech narsa yozilmadi. Yozish uchun --apply bering.")
        else:
            print(
                "\nTayyor. Natijalar Web App'da yangilanadi; "
                "Telegram xabari eski bo'lsa — alohida yuboriladi."
            )
        return 0
    finally:
        await db.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_main(args))
    except Exception as exc:  # foydalanuvchiga tushunarli xato
        print(f"Xatolik: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
