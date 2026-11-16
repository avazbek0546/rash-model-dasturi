"""Imtihon javoblaridan Rasch 1PL `b` ni avtomatik kalibrlash.

Misollar::

    # Preview (hech narsa yozilmaydi)
    python scripts/calibrate_item_bank.py --test-code m3rash25

    # 10 000+ javobdan kalibrlab, examga yozish
    python scripts/calibrate_item_bank.py --test-code m3rash25 --min-n 200 --apply

    # Mavjud bankni prior sifatida ishlatish
    python scripts/calibrate_item_bank.py --test-code m3rash25 \
        --prior-file assets/item_banks/m3rash25.json --apply

Xavfsizlik: standart rejim — **dry-run**. Yozish uchun `--apply`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import calibration, item_bank  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rasch 1PL JMLE kalibrlash")
    parser.add_argument("--test-code", default="", help="Imtihon test kodi")
    parser.add_argument("--exam-id", type=int, default=0, help="Imtihon ID")
    parser.add_argument(
        "--source",
        choices=("online", "offline", "combined"),
        default="combined",
        help="Javob manbasi (default: combined)",
    )
    parser.add_argument("--min-n", type=int, default=200, help="Minimal N (default 200)")
    parser.add_argument("--max-iter", type=int, default=100, help="Maksimal iteratsiya")
    parser.add_argument("--tol", type=float, default=1e-4, help="Konvergentsiya toleransi")
    parser.add_argument("--prior-file", default="", help="Ixtiyoriy oldingi item bank JSON")
    parser.add_argument("--out", default="", help="Natijani JSON faylga yozish")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Natijani exams.difficulty_logits ga yozish",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    db = Database(config.DB_PATH)
    await db.connect()
    try:
        repos = Repositories(db)
        exam = None
        if args.exam_id:
            exam = await repos.exams.get(int(args.exam_id))
        elif args.test_code:
            exam = await repos.exams.get_by_code(args.test_code)
        if exam is None:
            print("Exam topilmadi. --exam-id yoki --test-code bering.")
            return 2

        matrix = await calibration.build_exam_matrix(
            repos, exam, source=args.source
        )
        prior_b = None
        if args.prior_file:
            bank = item_bank.load_item_bank(args.prior_file)
            prior_b = dict(bank.b_by_label)
            print(f"Prior: {bank.test_code} — {bank.item_count} item")

        result = calibration.calibrate_rasch(
            matrix.matrix,
            matrix.labels,
            min_n=int(args.min_n),
            max_iter=int(args.max_iter),
            tol=float(args.tol),
            prior_b=prior_b,
        )
        print(f"Exam: #{exam.exam_id} {exam.test_code} — {exam.title}")
        print(
            f"N={result.person_count} (online={matrix.online_count}, "
            f"offline={matrix.offline_count}, excluded_online={matrix.excluded_online})"
        )
        print(
            f"K={result.item_count}, iter={result.iterations}, "
            f"converged={result.converged}, max_delta={result.max_delta:.8f}"
        )
        print(
            f"b: mean={result.b_mean:+.4f}, min={result.b_min:+.4f}, "
            f"max={result.b_max:+.4f}, theta_sd={result.theta_sd:.4f}"
        )
        if result.warnings:
            for warning in result.warnings:
                print(f"⚠️ {warning}")

        ranked = sorted(result.b_by_label.items(), key=lambda pair: pair[1])
        print("Eng oson: " + ", ".join(f"{k}={v:+.2f}" for k, v in ranked[:5]))
        print("Eng qiyin: " + ", ".join(f"{k}={v:+.2f}" for k, v in ranked[-5:]))

        payload = result.to_dict()
        if args.out:
            Path(args.out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"JSON: {args.out}")

        if not args.apply:
            print("DRY-RUN: yozilmadi. Yozish uchun --apply bering.")
            return 0

        b_json = await calibration.apply_calibration(repos, exam, result)
        print("OK: kalibrlangan b examga yozildi.")
        print(f"b_json (birinchi 160): {b_json[:160]}…")
        print("Keyingi qadam: regrade (POST /api/v2/admin/exams/{id}/regrade).")
        return 0
    finally:
        await db.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_main(args))
    except calibration.CalibrationError as exc:
        print(f"Kalibrlash xatosi: {exc}")
        return 2
    except item_bank.ItemBankError as exc:
        print(f"Item bank xatosi: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
