"""Item bankni (per-item `b`) examga yuklash.

Misol::

    python scripts/load_item_bank.py --file assets/item_banks/m3rash25.json
    python scripts/load_item_bank.py --file ... --test-code m3rash25 --apply
    python scripts/load_item_bank.py --file ... --exam-id 12 --apply

Skript `exams.difficulty_logits` ni JSON obyekt (`{"36a": ..., "45b": ...}`)
bilan yangilaydi. Baholash `services.exam_service.b_by_key()` orqali o'qiydi;
per-item kalitlar bo'lsa `THETA_METHOD=auto` avtomatik **EAP** ni tanlaydi.

Xavfsizlik: standart rejim — **dry-run** (hech narsa yozilmaydi). Yozish uchun
`--apply` bering.
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
from services import item_bank  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Item bankni examga yuklash")
    parser.add_argument("--file", required=True, help="Item bank JSON fayli")
    parser.add_argument("--test-code", default="", help="Imtihon test kodi")
    parser.add_argument("--exam-id", type=int, default=0, help="Imtihon ID")
    parser.add_argument(
        "--total-questions",
        type=int,
        default=0,
        help="Pozitsiyalar soni (0 — examdan olinadi)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Haqiqatan yozish (berilmasa — faqat dry-run)",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    bank = item_bank.load_item_bank(args.file)
    total = int(args.total_questions or 0)
    if total:
        bank.validate_labels(total)

    db = Database(config.DB_PATH)
    await db.connect()
    try:
        repos = Repositories(db)
        exam = None
        if args.exam_id:
            exam = await repos.exams.get(int(args.exam_id))
        elif args.test_code:
            exam = await repos.exams.get_by_code(args.test_code)
        else:
            exam = await repos.exams.get_by_code(bank.test_code)
        if exam is None:
            print("Exam topilmadi. --exam-id yoki --test-code bering.")
            return 2

        if not total:
            bank.validate_labels(int(exam.total_questions))
        print(f"Exam: #{exam.exam_id} {exam.test_code} — {exam.title}")
        print(f"Bank: {bank.test_code} — {bank.item_count} item")
        print(f"prior_sd: {bank.prior_sd if bank.prior_sd is not None else '(config)'}")
        print(f"source: {bank.source or '—'}")
        if bank.prior_sd is not None:
            print(
                "Eslatma: prior_sd examda saqlanmaydi; kerak bo'lsa "
                f"EAP_PRIOR_SD={bank.prior_sd} muhit o'zgaruvchisini bering."
            )
        print(f"b_json (birinchi 160 belgi): {bank.b_json()[:160]}…")

        if not args.apply:
            print("DRY-RUN: yozilmadi. Yozish uchun --apply bering.")
            return 0

        await repos.exams.update_difficulty_logits(exam.exam_id, bank.b_json())
        print("OK: item bank examga yozildi.")
        print("Keyingi qadam: imtihonni qayta baholash (regrade).")
        return 0
    finally:
        await db.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_main(args))
    except item_bank.ItemBankError as exc:
        print(f"Item bank xatosi: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
