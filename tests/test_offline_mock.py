"""Offline mock import — o'z-o'zini tekshirish testlari.

Ishga tushirish:
    python tests/test_offline_mock.py
"""

from __future__ import annotations

import asyncio
import io
import math
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from openpyxl import load_workbook  # noqa: E402

import config  # noqa: E402

config.DIFFICULTY_SHRINKAGE_ENABLED = False

from database.db import Database  # noqa: E402
from database.models import User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_admin, exam_service, form_layout, grading, offline_import  # noqa: E402
from services import offline_report, offline_scoring, offline_template, report_pdf, test_quality  # noqa: E402
from services import calibration  # noqa: E402

ADMIN_ID = 900001
ALI_ID = 900101
VALI_ID = 900102
LATE_ID = 900103
KEY = None
FLAGS_ALL = [1] * 55
FLAGS_HALF = ([1] * 28) + ([0] * 27)
FLAGS_VALI = ([1] * 20) + ([0] * 35)


def make_key() -> str:
    letters = ["A"] * 35
    numeric = {}
    for position in range(36, 46):
        numeric[f"{position}a"] = str(position - 35)
        numeric[f"{position}b"] = str(position - 30)
    return form_layout.build_canonical(letters, numeric)


def fill_template(template: bytes, rows: list[tuple[str, str, str, str | None, list[int]]]) -> bytes:
    wb = load_workbook(io.BytesIO(template))
    ws = wb["Natijalar"]
    for index, (code, name, klass, username, flags) in enumerate(rows, start=2):
        ws.cell(row=index, column=1, value=code)
        ws.cell(row=index, column=2, value=name)
        ws.cell(row=index, column=3, value=klass)
        ws.cell(row=index, column=4, value=username)
        for offset, flag in enumerate(flags, start=5):
            ws.cell(row=index, column=offset, value=flag)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()



async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="offline_mock_"))
    db = Database(tmp / "offline.db")
    await db.connect()
    repos = Repositories(db)
    try:
        await repos.users.upsert(User(user_id=ADMIN_ID, full_name="Admin"))
        await repos.users.upsert(User(user_id=ALI_ID, full_name="Ali Valiyev", username="ali_valiyev"))
        await repos.users.upsert(User(user_id=VALI_ID, full_name="Vali Karimov", username="vali_karimov"))

        same_key = make_key()
        assert offline_scoring.keys_are_equivalent(same_key, same_key, 45)
        assert not offline_scoring.keys_are_equivalent(
            same_key, same_key.replace("36a:1", "36a:2"), 45
        )
        print("[check] answer-key equivalence: same accepted, changed rejected")

        created = await create_exam(repos)
        exam = await repos.exams.get(created.exam_id)
        assert exam is not None
        readiness = await offline_scoring.check_readiness(repos, exam)
        print("[check] ready:", readiness.ready, "| items:", len(readiness.items), "| scored:", readiness.scored_items)
        assert readiness.ready, readiness.reason
        assert len(readiness.items) == 55 and readiness.scored_items == 55
        assert readiness.labels[:3] == ("1", "2", "3")
        assert readiness.labels[-2:] == ("45a", "45b")

        template = offline_template.build_template(exam, readiness)
        assert template[:2] == b"PK"
        print("[check] template bytes:", len(template))

        workbook = fill_template(
            template,
            [
                ("7A-01", "Ali Valiyev", "7A", "ali_valiyev", FLAGS_ALL),
                ("7A-02", "Dilnoza Karimova", "7A", None, FLAGS_HALF),
            ],
        )
        preview = await offline_import.stage_batch(
            repos, exam, readiness, workbook, "mock.xlsx", ADMIN_ID
        )
        print("[check] preview:", preview.can_commit, preview.error_count, preview.warning_count)
        assert preview.can_commit, preview.issues

        commit = await offline_import.commit_batch(repos, int(preview.batch["batch_id"]), ADMIN_ID)
        print("[check] commit:", commit)
        assert commit.participants == 2 and commit.attempts == 2
        assert await repos.offline_attempts.count_for_exam(exam.exam_id) == 2
        offline_rows = await repos.offline_attempts.list_for_exam(exam.exam_id)
        assert len(offline_rows) == 2
        assert all(int(row["total_items"]) == 55 for row in offline_rows)

        participants = await repos.offline_participants.list_for_exam(exam.exam_id)
        ali = next(p for p in participants if p["student_code"] == "7A-01")
        # Exceldagi username botdagi username bilan aynan mos — avtomatik link.
        assert ali["match_status"] == "confirmed", ali
        assert ali["match_method"] == "username_auto", ali
        assert int(ali["matched_user_id"]) == ALI_ID
        dilnoza = next(p for p in participants if p["student_code"] == "7A-02")
        assert dilnoza["match_status"] == "unmatched", dilnoza
        print("[check] exact username auto-linked; offline-only participant unmatched")

        ali_canonical = form_layout.build_canonical(
            ["A"] * 35,
            {f"{p}{part}": (str(p - 35) if part == "a" else str(p - 30))
             for p in range(36, 46) for part in ("a", "b")},
        )
        vali_canonical = form_layout.build_canonical(
            ["A"] * 35, {f"{p}a": str(p - 35) for p in range(36, 40)}
        )
        await repos.answers.submit(user_id=ALI_ID, exam_id=exam.exam_id, submitted_answers=ali_canonical)
        await repos.answers.submit(user_id=VALI_ID, exam_id=exam.exam_id, submitted_answers=vali_canonical)
        await grading.grade_exam(repos, exam)
        exam = await repos.exams.get(exam.exam_id)
        assert exam is not None

        excluded = await offline_import.ensure_ranking_decisions(repos, exam.exam_id)
        print("[check] ranking excluded:", excluded)
        assert excluded == 1

        # Online natija tarixda qoladi, lekin reytingda ikkinchi marta chiqmaydi.
        online_ali = await repos.answers.get(ALI_ID, exam.exam_id)
        assert online_ali is not None and online_ali.theta is not None
        online_report = grading.build_report(exam, online_ali)
        offline_ali = next(
            row for row in offline_rows if row["student_code"] == "7A-01"
        )
        assert math.isclose(
            float(online_report["theta"]), float(offline_ali["theta"]), abs_tol=1e-9
        )
        assert math.isclose(
            float(online_report["scaled_score"]),
            float(offline_ali["scaled_score"]),
            abs_tol=1e-9,
        )
        print(
            "[check] same Rasch result: theta=%.4f, ball=%.2f"
            % (float(offline_ali["theta"]), float(offline_ali["scaled_score"]))
        )

        combined = await offline_report.build_combined_report(repos, exam)
        print("[check] combined:", combined.participants, combined.offline_count, combined.online_count, combined.excluded_count)
        assert combined.participants == 3
        assert combined.offline_count == 2
        assert combined.online_count == 1
        assert combined.excluded_count == 1
        assert all(row.total == 55 for row in combined.students)

        # Test sifati: offline va combined manbalar (offline 2, online 1)
        offline_quality = await test_quality.build_exam_quality(
            repos, exam, source="offline"
        )
        assert offline_quality["source"] == "offline", offline_quality
        assert offline_quality["summary"]["participants"] == 2, offline_quality
        assert offline_quality["summary"]["items"] == 55, offline_quality
        combined_quality = await test_quality.build_exam_quality(
            repos, exam, source="combined"
        )
        assert combined_quality["source"] == "combined", combined_quality
        assert combined_quality["summary"]["participants"] == 3, combined_quality
        assert combined_quality["summary"]["online_participants"] == 1
        assert combined_quality["summary"]["offline_participants"] == 2
        print(
            "[OK] Test sifati: offline=2, combined=3 (online 1 + offline 2)"
        )

        # Avtomatik kalibrlash matritsasi: 1 online + 2 offline, 55 item
        calibration_matrix = await calibration.build_exam_matrix(
            repos, exam, source="combined"
        )
        assert calibration_matrix.online_count == 1
        assert calibration_matrix.offline_count == 2
        assert len(calibration_matrix.labels) == 55
        calibration_result = calibration.calibrate_rasch(
            calibration_matrix.matrix,
            calibration_matrix.labels,
            min_n=1,
            max_iter=10,
        )
        assert calibration_result.person_count == 3
        assert calibration_result.item_count == 55
        print("[OK] Kalibrlash matritsasi: N=3, K=55 (online 1 + offline 2)")
        assert len(combined.students) == 3 and combined.students[0].rank == 1

        pdf_combined = report_pdf.build_combined_results_pdf(
            meta=combined.meta, students=list(combined.students)
        )
        assert pdf_combined[:4] == b"%PDF"
        print("[check] combined PDF:", len(pdf_combined))

        # Bog'lanish bekor qilinsa, online natija reytingga qaytadi.
        await offline_import.unlink_participant(
            repos, participant_id=int(ali["participant_id"]), admin_id=ADMIN_ID
        )
        unlinked = await offline_report.build_combined_report(repos, exam)
        print(
            "[check] unlinked:",
            unlinked.participants,
            unlinked.offline_count,
            unlinked.online_count,
            unlinked.excluded_count,
        )
        assert unlinked.participants == 4
        assert unlinked.offline_count == 2
        assert unlinked.online_count == 2
        assert unlinked.excluded_count == 0
        assert await repos.answers.get(ALI_ID, exam.exam_id) is not None

        # Qo'lda qayta bog'lash ham ishlaydi (offline yana asosiy bo'ladi).
        await offline_import.link_participant(
            repos, participant_id=int(ali["participant_id"]), user_id=ALI_ID,
            admin_id=ADMIN_ID, method="manual",
        )
        relinked = await offline_report.build_combined_report(repos, exam)
        assert relinked.participants == 3 and relinked.excluded_count == 1
        print("[check] unlink/relink OK")

        offline = await offline_report.build_offline_report(repos, exam)
        print("[check] offline report:", offline.participants, len(offline.students), [(s.name, s.source, s.total) for s in offline.students])
        assert offline.participants == 2
        assert all(row.source == "offline" and row.total == 55 for row in offline.students)
        pdf_offline = report_pdf.build_offline_results_pdf(
            meta=offline.meta, students=list(offline.students)
        )
        assert pdf_offline[:4] == b"%PDF"
        print("[check] offline PDF:", len(pdf_offline))

        try:
            await offline_import.stage_batch(repos, exam, readiness, workbook, "mock.xlsx", ADMIN_ID)
        except offline_import.OfflineImportError as exc:
            print("[check] duplicate rejected:", str(exc)[:60])
        else:
            raise AssertionError("Takroriy fayl qabul qilindi")

        # Meta o'zgartirilgan (boshqa imtihondan olingan) fayl qabul qilinmaydi.
        meta_wb = load_workbook(io.BytesIO(workbook))
        meta_ws = meta_wb["Meta"]
        for row_no in range(2, meta_ws.max_row + 1):
            if meta_ws.cell(row=row_no, column=1).value == "key_fingerprint":
                meta_ws.cell(row=row_no, column=2, value="0" * 64)
                break
        meta_buf = io.BytesIO()
        meta_wb.save(meta_buf)
        meta_preview = await offline_import.stage_batch(
            repos, exam, readiness, meta_buf.getvalue(), "meta.xlsx", ADMIN_ID
        )
        print("[check] meta mismatch:", meta_preview.error_count, meta_preview.issues[:3])
        assert not meta_preview.can_commit
        assert any(
            issue.get("code") == "META_MISMATCH"
            for issue in meta_preview.issues
        )
        await offline_import.void_batch(
            repos, int(meta_preview.batch["batch_id"]), ADMIN_ID, "test meta"
        )

        bad_wb = load_workbook(io.BytesIO(workbook))
        bad_wb["Natijalar"].cell(row=2, column=5, value="x")
        bad_buf = io.BytesIO()
        bad_wb.save(bad_buf)
        bad_preview = await offline_import.stage_batch(
            repos, exam, readiness, bad_buf.getvalue(), "bad.xlsx", ADMIN_ID
        )
        print("[check] invalid counts:", bad_preview.error_count, bad_preview.warning_count)
        print("[check] invalid issues:", bad_preview.issues[:3])
        assert not bad_preview.can_commit and bad_preview.error_count > 0
        print("[check] invalid rejected:", bad_preview.error_count)

        await offline_import.void_batch(repos, int(preview.batch["batch_id"]), ADMIN_ID, "test")
        print("[check] attempts after void:", await repos.offline_attempts.list_for_exam(exam.exam_id, include_void=True))
        after_void = await offline_report.build_combined_report(repos, exam)
        print("[check] after void:", after_void.participants, after_void.offline_count, after_void.online_count)
        assert after_void.offline_count == 0
        assert after_void.online_count == 2
        assert after_void.participants == 2

        # Import paytida hali botda yo'q o'quvchi keyin ro'yxatdan o'tsa,
        # hisobot bosqichida username orqali avtomatik bog'lanadi.
        late_wb = fill_template(
            template,
            [("7A-03", "Late Student", "7A", "late_student", FLAGS_HALF)],
        )
        late_preview = await offline_import.stage_batch(
            repos, exam, readiness, late_wb, "late.xlsx", ADMIN_ID
        )
        assert late_preview.can_commit
        await offline_import.commit_batch(
            repos, int(late_preview.batch["batch_id"]), ADMIN_ID
        )
        late = next(
            p for p in await repos.offline_participants.list_for_exam(exam.exam_id)
            if p["student_code"] == "7A-03"
        )
        assert late["match_status"] == "unmatched", late
        await repos.users.upsert(
            User(user_id=LATE_ID, full_name="Late Student", username="late_student")
        )
        late_report = await offline_report.build_combined_report(repos, exam)
        late = await repos.offline_participants.get(int(late["participant_id"]))
        assert late is not None
        assert late["match_status"] == "confirmed", late
        assert late["match_method"] == "username_auto", late
        assert int(late["matched_user_id"]) == LATE_ID
        print("[check] late registration auto-link:", late_report.participants)

        # Ism bo'yicha avtomatik bog'lash: offline o'quvchi bilan bir xil ismli
        # foydalanuvchi shu imtihonda onlayn qatnashsa — bitta qatorga qo'shiladi
        # (offline + online natija aralashmay, dublikat bo'lmaydi).
        DILNOZA_ID = 900104
        await repos.users.upsert(
            User(user_id=DILNOZA_ID, full_name="Dilnoza Karimova", username=None)
        )
        await repos.answers.submit(
            user_id=DILNOZA_ID, exam_id=exam.exam_id, submitted_answers=ali_canonical
        )
        await grading.grade_exam(repos, exam)
        exam = await repos.exams.get(exam.exam_id)
        assert exam is not None
        await offline_import.refresh_suggestions(repos, exam.exam_id)
        dilnoza = next(
            p for p in await repos.offline_participants.list_for_exam(exam.exam_id)
            if p["student_code"] == "7A-02"
        )
        assert dilnoza["match_status"] == "confirmed", dilnoza
        assert dilnoza["match_method"] == "name_auto", dilnoza
        assert int(dilnoza["matched_user_id"]) == DILNOZA_ID
        print("[check] unique online name auto-linked (name_auto)")

        # Partiyani butunlay o'chirish: qatorlar, attemptlar va ishtirokchi
        # bazadan yo'qoladi (void'dan farqi — tarix qolmaydi).
        late_batch_id = int(late_preview.batch["batch_id"])
        delete_stats = await offline_import.delete_batch(repos, late_batch_id, ADMIN_ID)
        print("[check] delete batch:", delete_stats)
        assert delete_stats["attempts"] == 1 and delete_stats["rows"] == 1
        assert await repos.offline_batches.get_batch(late_batch_id) is None
        assert await repos.offline_participants.get(int(late["participant_id"])) is None
        assert await repos.offline_attempts.count_for_exam(exam.exam_id) == 0
        print("[check] batch hard-delete removes rows, attempts and participants")

        # Imtihon o'chirilsa, offline tarix ham CASCADE bilan tozalanadi.
        await repos.exams.delete(exam.exam_id)
        assert await repos.offline_attempts.count_for_exam(exam.exam_id) == 0
        print("[check] exam delete cascades offline history")

        print("=" * 72)
        print("Barcha offline mock testlari muvaffaqiyatli o'tdi ✅")
    finally:
        await db.close()


async def create_exam(repos: Repositories):
    now = datetime.now(timezone.utc)
    return await exam_admin.create_exam(
        repos,
        title="Mock 55 offline test",
        test_code="MOCK55",
        total_questions=45,
        answer_key=make_key(),
        difficulty=[0.0] * 45,
        start_time=exam_service.to_db_time(now + timedelta(hours=1)),
        end_time=exam_service.to_db_time(now + timedelta(hours=2)),
        result_time=exam_service.to_db_time(now + timedelta(hours=3)),
        created_by=ADMIN_ID,
    )


if __name__ == "__main__":
    asyncio.run(main())

