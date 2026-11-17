"""Offline Excel import: parse → validate → preview → commit → void.

Fayl avval to'liq tekshiriladi; admin tasdiqlamaguncha `offline_attempts`
ga hech narsa yozilmaydi. Commit bitta tranzaksiyada bo'ladi.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from openpyxl import load_workbook

import config
from database.models import Exam
from database.offline_norm import clean_text, normalize_code, normalize_name, normalize_username
from database.repository import Repositories
from services import offline_scoring
from services.offline_scoring import OfflineReadiness
from services.offline_template import BASE_HEADERS, SHEET_HELP, SHEET_META, SHEET_RESULTS

logger = logging.getLogger(__name__)

MAX_ROWS = int(config.OFFLINE_IMPORT_MAX_ROWS)
MAX_FILE_MB = int(config.OFFLINE_IMPORT_MAX_MB)


class OfflineImportError(ValueError):
    """Foydalanuvchiga ko'rsatiladigan import xatosi."""


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row_no: int
    student_code: str
    student_code_norm: str
    full_name: str
    full_name_norm: str
    class_label: str
    telegram_username: str | None
    flags: tuple[int, ...]
    row_status: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedWorkbook:
    rows: tuple[ParsedRow, ...]
    issues: tuple[dict[str, Any], ...]
    meta: dict[str, str]
    meta_ok: bool


@dataclass(frozen=True, slots=True)
class BatchPreview:
    batch: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    issues: tuple[dict[str, Any], ...]
    error_count: int
    warning_count: int
    can_commit: bool


@dataclass(frozen=True, slots=True)
class CommitResult:
    batch_id: int
    participants: int
    created: int
    updated: int
    attempts: int
    offline_count: int
    online_excluded: int = 0


@dataclass(slots=True)
class _CommitRow:
    row_no: int
    student_code: str
    student_code_norm: str
    full_name: str
    full_name_norm: str
    class_label: str
    telegram_username: str | None
    flags: tuple[int, ...]
    score: offline_scoring.OfflineScore
    responses: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cell_text(value: Any) -> str:
    return "" if value is None else clean_text(value, limit=400)


def _meta_dict(ws: Any) -> dict[str, str]:
    meta: dict[str, str] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        key = _cell_text(row[0] if len(row) > 0 else "")
        value = _cell_text(row[1] if len(row) > 1 else "")
        if key:
            meta[key] = value
    return meta


def _binary(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, float) and value in (0.0, 1.0):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text in ("0", "1"):
            return int(text)
    return None


def parse_workbook(
    data: bytes, exam: Exam, readiness: OfflineReadiness
) -> ParsedWorkbook:
    """`.xlsx` faylni o'qiydi va barcha qatorlarni tekshiradi."""
    if not data:
        raise OfflineImportError("Fayl bo'sh.")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise OfflineImportError(f"Fayl hajmi {MAX_FILE_MB} MB dan oshmasligi kerak.")
    if not readiness.ready:
        raise OfflineImportError(readiness.reason)
    try:
        wb_struct = load_workbook(io.BytesIO(data), data_only=False, read_only=False)
        wb_values = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:
        raise OfflineImportError(f"Excel faylni o'qib bo'lmadi: {exc}") from exc

    issues: list[dict[str, Any]] = []
    meta: dict[str, str] = {}
    meta_ok = True

    if SHEET_RESULTS not in wb_values.sheetnames:
        raise OfflineImportError(
            f"`{SHEET_RESULTS}` varag'i topilmadi. Bot bergan shablonni ishlating."
        )
    extra = set(wb_values.sheetnames) - {SHEET_RESULTS, SHEET_META, SHEET_HELP}
    if extra:
        issues.append({"code": "EXTRA_SHEET", "message": f"Ortiqcha varaq(lar): {', '.join(sorted(extra))}", "severity": "error"})
        meta_ok = False

    ws_meta = wb_values[SHEET_META] if SHEET_META in wb_values.sheetnames else None
    if ws_meta is None:
        issues.append({"code": "META_MISSING", "message": "`Meta` varag'i yo'q.", "severity": "error"})
        meta_ok = False
    else:
        meta = _meta_dict(ws_meta)

    expected_headers = list(BASE_HEADERS) + list(readiness.labels)
    ws_struct = wb_struct[SHEET_RESULTS]
    ws_values = wb_values[SHEET_RESULTS]
    actual_headers = [
        _cell_text(cell.value)
        for cell in next(ws_struct.iter_rows(min_row=1, max_row=1, max_col=len(expected_headers)))
    ]
    if actual_headers != expected_headers:
        issues.append({"code": "HEADER_MISMATCH", "message": "Ustunlar soni yoki tartibi shablondan farq qiladi.", "severity": "error"})
        meta_ok = False
    if ws_struct.max_column > len(expected_headers):
        issues.append({"code": "EXTRA_COLUMN", "message": "Ortiqcha ustun bor.", "severity": "error"})
        meta_ok = False

    for merged in ws_struct.merged_cells.ranges:
        if merged.min_row >= 1 and merged.min_col >= 1:
            issues.append({"code": "MERGED_CELL", "message": "Birlashtirilgan katak topildi.", "severity": "error"})
            meta_ok = False
            break
    for row_index, dimensions in ws_struct.row_dimensions.items():
        if dimensions.hidden and row_index >= 1:
            issues.append({"row_no": int(row_index), "code": "HIDDEN_ROW", "message": "Yashirin qator topildi.", "severity": "warning"})
    for column_index, dimensions in ws_struct.column_dimensions.items():
        if dimensions.hidden:
            issues.append({"column_name": str(column_index), "code": "HIDDEN_COLUMN", "message": "Yashirin ustun topildi.", "severity": "warning"})

    required_meta = (
        "test_code", "form_version_id", "total_items",
        "labels_order_hash", "key_fingerprint", "b_checksum",
    )
    for key in required_meta:
        if not meta.get(key):
            issues.append({"code": "META_FIELD_MISSING", "message": f"`Meta` da `{key}` yo'q.", "severity": "error"})
            meta_ok = False
    checks = {
        "test_code": str(exam.test_code),
        "form_version_id": str(readiness.form_version_id or ""),
        "total_items": str(len(readiness.labels)),
        "labels_order_hash": readiness.labels_order_hash,
        "key_fingerprint": readiness.key_fingerprint,
        "b_checksum": readiness.b_checksum,
    }
    for key, expected in checks.items():
        actual = meta.get(key)
        if not actual:
            # Yo'qligi yuqorida META_FIELD_MISSING sifatida allaqachon belgilangan.
            continue
        if actual != expected:
            issues.append(
                {
                    "code": "META_MISMATCH",
                    "message": (
                        f"`Meta` dagi `{key}` joriy imtihonga mos emas. "
                        "Shablon eskirgan yoki boshqa testdan olingan."
                    ),
                    "severity": "error",
                }
            )
            meta_ok = False

    max_row = min(int(ws_struct.max_row or 0), MAX_ROWS + 1)
    if int(ws_struct.max_row or 0) - 1 > MAX_ROWS:
        issues.append({"code": "TOO_MANY_ROWS", "message": f"Qatorlar soni {MAX_ROWS} dan oshmasligi kerak.", "severity": "error"})
        meta_ok = False
    formula_found = False
    for row in ws_struct.iter_rows(min_row=2, max_row=max_row, min_col=1, max_col=len(expected_headers)):
        for cell in row:
            if cell.data_type == "f":
                issues.append({"row_no": int(cell.row), "column_name": str(cell.column_letter), "code": "FORMULA_NOT_ALLOWED", "message": "Formuladan foydalanmang; 0 yoki 1 yozing.", "severity": "error"})
                meta_ok = False
                formula_found = True
                break
        if formula_found:
            break

    rows: list[ParsedRow] = []
    seen_codes: dict[str, int] = {}
    seen_names: dict[tuple[str, str], int] = {}
    seen_data = False
    blank_after_data = False
    values_iter = ws_values.iter_rows(min_row=2, max_row=max_row, max_col=len(expected_headers), values_only=True)
    for offset, values in enumerate(values_iter, start=2):
        cells = list(values)
        if all(_cell_text(value) == "" for value in cells):
            if seen_data:
                blank_after_data = True
            continue
        if blank_after_data:
            issues.append({"row_no": offset, "code": "GAP_ROW", "message": "Ma'lumotlar orasida bo'sh qator bor.", "severity": "error"})

        row_issues: list[dict[str, Any]] = []
        student_code = _cell_text(cells[0] if len(cells) > 0 else "")
        full_name = _cell_text(cells[1] if len(cells) > 1 else "")
        class_label = _cell_text(cells[2] if len(cells) > 2 else "")
        raw_username = _cell_text(cells[3] if len(cells) > 3 else "")
        username = normalize_username(raw_username) if raw_username else None
        if raw_username and username is None:
            row_issues.append({"row_no": offset, "code": "BAD_USERNAME", "message": "`telegram_username` formati noto'g'ri; bo'sh qoldirildi.", "severity": "warning"})
        if not student_code:
            row_issues.append({"row_no": offset, "code": "MISSING_CODE", "message": "`student_code` bo'sh.", "severity": "error"})
        elif len(student_code) > 32:
            row_issues.append({"row_no": offset, "code": "CODE_TOO_LONG", "message": "`student_code` 32 belgidan oshmasin.", "severity": "error"})
        if not full_name:
            row_issues.append({"row_no": offset, "code": "MISSING_NAME", "message": "`full_name` bo'sh.", "severity": "error"})
        elif len(full_name) > 120:
            row_issues.append({"row_no": offset, "code": "NAME_TOO_LONG", "message": "`full_name` 120 belgidan oshmasin.", "severity": "error"})
        if not class_label:
            row_issues.append({
                "row_no": offset, "code": "MISSING_CLASS",
                "message": "`class` bo'sh — sinf ko'rsatilmaydi (ixtiyoriy).",
                "severity": "warning",
            })

        code_norm = normalize_code(student_code)
        if code_norm:
            if code_norm in seen_codes:
                row_issues.append({"row_no": offset, "code": "DUPLICATE_CODE", "message": f"`student_code` {seen_codes[code_norm]}-qatorda ham bor.", "severity": "error"})
            else:
                seen_codes[code_norm] = offset
        name_norm = normalize_name(full_name)
        name_key = (name_norm, normalize_name(class_label))
        if full_name and class_label:
            if name_key in seen_names:
                row_issues.append({"row_no": offset, "code": "DUPLICATE_NAME_CLASS", "message": "Bir xil ism va sinf boshqa qatorda ham bor.", "severity": "warning"})
            else:
                seen_names[name_key] = offset

        flags: list[int] = []
        for index, label in enumerate(readiness.labels):
            value = cells[4 + index] if len(cells) > 4 + index else None
            flag = _binary(value)
            if flag is None:
                row_issues.append({"row_no": offset, "column_name": label, "code": "BAD_BINARY", "message": f"{label}-topshiriq uchun faqat 0 yoki 1 kiriting.", "severity": "error"})
                flag = 0
            flags.append(flag)

        issues.extend(row_issues)
        status = "error" if any(i["severity"] == "error" for i in row_issues) else ("warning" if row_issues else "valid")
        first_error = next((i for i in row_issues if i["severity"] == "error"), row_issues[0] if row_issues else None)
        rows.append(ParsedRow(
            row_no=offset, student_code=student_code, student_code_norm=code_norm,
            full_name=full_name, full_name_norm=name_norm, class_label=class_label,
            telegram_username=username, flags=tuple(flags), row_status=status,
            error_code=(first_error or {}).get("code"),
            error_message=(first_error or {}).get("message"),
        ))
        seen_data = True

    if not rows:
        issues.append({"code": "NO_ROWS", "message": "Faylda birorta o'quvchi qatori yo'q.", "severity": "error"})
        meta_ok = False
    wb_struct.close()
    wb_values.close()
    return ParsedWorkbook(rows=tuple(rows), issues=tuple(issues), meta=meta, meta_ok=meta_ok)


async def _audit(
    repos: Repositories, *, admin_id: int, action: str,
    entity_type: str, entity_id: int | str,
    before: Any = None, after: Any = None, note: str = "",
) -> None:
    await repos.db.execute(
        """
        INSERT INTO audit_log (
            actor_user_id, action, entity_type, entity_id,
            before_json, after_json, source, note
        ) VALUES (?, ?, ?, ?, ?, ?, 'bot', ?)
        """,
        (
            int(admin_id), action, entity_type, str(entity_id),
            None if before is None else json.dumps(before, ensure_ascii=False),
            None if after is None else json.dumps(after, ensure_ascii=False),
            note,
        ),
    )


async def stage_batch(
    repos: Repositories, exam: Exam, readiness: OfflineReadiness,
    data: bytes, filename: str, admin_id: int,
) -> BatchPreview:
    """Faylni tekshiradi va `draft`/`validated` partiya yaratadi."""
    digest = _file_hash(data)
    active = await repos.offline_batches.active_by_hash(exam.exam_id, digest)
    if active is not None:
        raise OfflineImportError(f"Bu fayl allaqachon #{active['batch_no']} partiyada yuklangan.")
    parsed = parse_workbook(data, exam, readiness)
    batch_id = await repos.offline_batches.create_batch(
        exam_id=exam.exam_id,
        form_version_id=int(readiness.form_version_id or 0),
        uploaded_by=admin_id,
        file_name=filename,
        file_sha256=digest,
        file_size=len(data),
        template_version=str(parsed.meta.get("template_version") or "1"),
        key_fingerprint=readiness.key_fingerprint,
        b_checksum=readiness.b_checksum,
        b_source=readiness.b_source,
        engine_version=readiness.engine_version,
    )
    await repos.offline_batches.add_rows(
        batch_id,
        (
            {
                "row_no": row.row_no, "student_code": row.student_code,
                "student_code_norm": row.student_code_norm,
                "full_name": row.full_name, "full_name_norm": row.full_name_norm,
                "class_label": row.class_label,
                "telegram_username": row.telegram_username,
                "flags": row.flags, "row_status": row.row_status,
                "error_code": row.error_code, "error_message": row.error_message,
            }
            for row in parsed.rows
        ),
    )
    await repos.offline_batches.add_issues(batch_id, parsed.issues)
    rows_error = sum(1 for row in parsed.rows if row.row_status == "error")
    rows_valid = len(parsed.rows) - rows_error
    error_count = sum(1 for issue in parsed.issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in parsed.issues if issue.get("severity") == "warning")
    if error_count == 0 and rows_valid > 0:
        await repos.offline_batches.mark_validated(
            batch_id, rows_total=len(parsed.rows),
            rows_valid=rows_valid, rows_invalid=rows_error,
        )
    batch = await repos.offline_batches.get_batch(batch_id) or {}
    await _audit(
        repos, admin_id=admin_id, action="offline.batch.stage",
        entity_type="offline_batch", entity_id=batch_id,
        after={"status": batch.get("status"), "rows": len(parsed.rows)}, note=filename,
    )
    return BatchPreview(
        batch=batch,
        rows=tuple(await repos.offline_batches.list_rows(batch_id)),
        issues=tuple(await repos.offline_batches.list_issues(batch_id)),
        error_count=error_count,
        warning_count=warning_count,
        can_commit=error_count == 0 and rows_valid > 0,
    )


async def commit_batch(repos: Repositories, batch_id: int, admin_id: int) -> CommitResult:
    """`validated` partiyani bitta tranzaksiyada bazaga yozadi."""
    batch = await repos.offline_batches.get_batch(batch_id)
    if batch is None:
        raise OfflineImportError("Import partiyasi topilmadi.")
    if str(batch.get("status")) != "validated":
        raise OfflineImportError("Partiya tasdiqlashga tayyor emas. Avval xatolarni tuzating.")
    exam = await repos.exams.get(int(batch["exam_id"]))
    if exam is None:
        raise OfflineImportError("Imtihon topilmadi.")
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        raise OfflineImportError(readiness.reason)
    if int(readiness.form_version_id or 0) != int(batch["form_version_id"]):
        raise OfflineImportError("Forma versiyasi o'zgargan — shablonni qayta yarating.")
    if readiness.key_fingerprint != str(batch["key_fingerprint"]):
        raise OfflineImportError("Javoblar kaliti o'zgargan — import bloklandi.")
    if readiness.b_checksum != str(batch["b_checksum"]):
        raise OfflineImportError("`b` parametrlari o'zgargan — import bloklandi.")

    rows = await repos.offline_batches.list_rows(batch_id)
    if not rows:
        raise OfflineImportError("Partiyada qatorlar yo'q.")
    if any(str(row.get("row_status")) == "error" for row in rows):
        raise OfflineImportError("Partiyada xatoli qatorlar bor — avval tuzating.")

    commit_rows: list[_CommitRow] = []
    for row in rows:
        code_norm = str(row["student_code_norm"])
        existing = await repos.offline_participants.get_by_code(exam.exam_id, code_norm)
        if existing is not None:
            attempt = await repos.offline_attempts.get_for_participant(
                exam.exam_id, int(existing["participant_id"])
            )
            if attempt is not None:
                raise OfflineImportError(
                    f"`{row['student_code']}` uchun allaqachon valid offline natija bor. "
                    "Avval eski partiyani bekor qiling."
                )
        flags = tuple(int(value) for value in row.get("flags") or ())
        score = offline_scoring.score_offline(exam, readiness, flags)
        commit_rows.append(_CommitRow(
            row_no=int(row["row_no"]), student_code=str(row["student_code"]),
            student_code_norm=code_norm, full_name=str(row["full_name"]),
            full_name_norm=str(row["full_name_norm"]),
            class_label=str(row.get("class_label") or ""),
            telegram_username=row.get("telegram_username"),
            flags=flags, score=score, responses=tuple(score.responses),
        ))

    payload = [
        {
            "row_no": row.row_no, "student_code": row.student_code,
            "student_code_norm": row.student_code_norm, "full_name": row.full_name,
            "full_name_norm": row.full_name_norm, "class_label": row.class_label,
            "telegram_username": row.telegram_username, "flags": row.flags,
            "score": row.score, "responses": row.responses,
        }
        for row in commit_rows
    ]
    stats = await repos.offline_batches.commit_batch(batch=batch, rows=payload, admin_id=admin_id)
    await refresh_suggestions(repos, exam.exam_id, admin_id=admin_id)
    await ensure_ranking_decisions(repos, exam.exam_id)
    excluded = [
        d for d in await repos.offline_decisions.list_active(exam.exam_id, source="online")
        if int(d.get("included_in_ranking") or 0) == 0
    ]
    await _audit(
        repos, admin_id=admin_id, action="offline.batch.commit",
        entity_type="offline_batch", entity_id=batch_id,
        after=stats, note=f"exam_id={exam.exam_id}",
    )
    return CommitResult(
        batch_id=batch_id, participants=int(stats.get("participants") or 0),
        created=int(stats.get("created") or 0), updated=int(stats.get("updated") or 0),
        attempts=int(stats.get("attempts") or 0),
        offline_count=await repos.offline_attempts.count_for_exam(exam.exam_id),
        online_excluded=len(excluded),
    )


async def void_batch(
    repos: Repositories, batch_id: int, admin_id: int, reason: str = "admin"
) -> dict[str, int]:
    """Partiyani bekor qiladi; natijalar tarixda qoladi."""
    batch = await repos.offline_batches.get_batch(batch_id)
    if batch is None:
        raise OfflineImportError("Import partiyasi topilmadi.")
    stats = await repos.offline_batches.void_batch(
        batch_id=batch_id, admin_id=admin_id, reason=reason
    )
    await ensure_ranking_decisions(repos, int(batch["exam_id"]))
    await _audit(
        repos, admin_id=admin_id, action="offline.batch.void",
        entity_type="offline_batch", entity_id=batch_id, after=stats, note=reason,
    )
    return stats


async def delete_batch(
    repos: Repositories, batch_id: int, admin_id: int
) -> dict[str, int]:
    """Partiyani va unga tegishli natijalarni bazadan butunlay o'chiradi.

    `void_batch` dan farqi: yozuvlar tarixda qolmaydi — qatorlar, attemptlar va
    boshqa partiyada qolmagan ishtirokchilar ham o'chadi. Reyting qarorlari
    qayta hisoblanadi, ya'ni bog'langan onlayn natijalar reytingga qaytadi.
    """
    batch = await repos.offline_batches.get_batch(batch_id)
    if batch is None:
        raise OfflineImportError("Import partiyasi topilmadi.")
    stats = await repos.offline_batches.delete_batch(batch_id=batch_id)
    await ensure_ranking_decisions(repos, int(batch["exam_id"]))
    await _audit(
        repos, admin_id=admin_id, action="offline.batch.delete",
        entity_type="offline_batch", entity_id=batch_id,
        before={
            "status": str(batch.get("status")),
            "file_name": str(batch.get("file_name") or ""),
        },
        after=stats,
    )
    return stats


async def refresh_suggestions(
    repos: Repositories, exam_id: int, *, admin_id: int = 0
) -> int:
    """Nomzodlarni yangilaydi va aniq mosliklarni avtomatik tasdiqlaydi.

    Ikki xil ishonchli moslik avtomatik tasdiqlanadi:

    **(1)** Exceldagi `telegram_username` botdagi username'ga **aynan** mos —
        ishonchli identifikator (`username_auto`);
    **(2)** ism bo'yicha yagona nomzod **shu imtihonda onlayn qatnashgan** —
        offline va online natija bitta qatorga qo'shiladi, reytingda dublikat
        bo'lmaydi (`name_auto`).

    Qolgan hollarda (bir nechta teng nomzod yoki faqat boshqa imtihondagi odam)
    faqat taklif qoladi: qarorni admin `/offline_links` orqali tasdiqlaydi.
    """
    participants = await repos.offline_participants.list_for_exam(exam_id)
    by_username, by_name = await repos.offline_participants.candidate_index()
    # Ism bo'yicha avtomatik bog'lash faqat shu imtihonda onlayn qatnashganlar
    # ichida qidiriladi — begona bir xil ismli odamga ulanib ketmasin.
    online_user_ids = {
        int(submission.user_id)
        for submission in await repos.answers.list_for_exam(exam_id)
    }
    updated = 0
    for participant in participants:
        # `rejected` — admin qo'lda uzgan; qayta avtomatik bog'lamaymiz.
        if str(participant.get("match_status")) in {"confirmed", "rejected"}:
            continue
        username = normalize_username(participant.get("telegram_username"))
        candidates = by_username.get(username.casefold(), []) if username else []
        match_kind = "username"
        if not candidates:
            name_candidates = by_name.get(
                str(participant.get("full_name_norm") or ""), []
            )
            online_candidates = [
                candidate
                for candidate in name_candidates
                if int(candidate["user_id"]) in online_user_ids
            ]
            if len(online_candidates) == 1:
                # Onlayn qatnashgan yagona ism — aniq moslik, avtomatik bog'lanadi.
                candidates = online_candidates
                match_kind = "name"
            else:
                candidates = name_candidates
                match_kind = "name_class"
        if len(candidates) == 1:
            candidate = candidates[0]
            if match_kind in {"username", "name"}:
                link_method = "username_auto" if match_kind == "username" else "name_auto"
                default_confidence = 0.95 if match_kind == "username" else 0.8
                await repos.offline_participants.confirm_link(
                    participant_id=int(participant["participant_id"]),
                    user_id=int(candidate["user_id"]),
                    admin_id=admin_id,
                    method=link_method,
                    confidence=float(
                        candidate.get("confidence") or default_confidence
                    ),
                )
                await _audit(
                    repos, admin_id=admin_id, action="offline.participant.auto_link",
                    entity_type="offline_participant",
                    entity_id=int(participant["participant_id"]),
                    after={
                        "user_id": int(candidate["user_id"]),
                        "method": link_method,
                    },
                )
            else:
                await repos.offline_participants.set_suggestion(
                    int(participant["participant_id"]),
                    user_id=int(candidate["user_id"]), status="suggested",
                    method=str(candidate.get("method") or "name_class"),
                    confidence=float(candidate.get("confidence") or 0.7),
                )
        elif len(candidates) > 1:
            await repos.offline_participants.set_suggestion(
                int(participant["participant_id"]), user_id=None,
                status="conflict", method="name_class", confidence=0.0,
            )
        else:
            await repos.offline_participants.set_suggestion(
                int(participant["participant_id"]), user_id=None,
                status="unmatched", method="", confidence=None,
            )
        updated += 1
    return updated


async def ensure_ranking_decisions(repos: Repositories, exam_id: int) -> int:
    """Reyting qarorlarini idempotent yangilaydi.

    Valid offline — rasmiy. Tasdiqlangan link orqali bog'langan online natija
    reytingdan chiqariladi. Boshqa online natijalar qoladi.
    """
    for attempt in await repos.offline_attempts.list_for_exam(exam_id):
        participant_id = int(attempt["participant_id"])
        active = await repos.offline_decisions.get_active(
            exam_id, "offline_participant", participant_id
        )
        if active is None or int(active.get("included_in_ranking") or 0) != 1:
            await repos.offline_decisions.upsert(
                exam_id=exam_id, subject_type="offline_participant",
                subject_id=participant_id, source="offline", included=1,
                reason="offline_official",
            )

    linked_user_ids: set[int] = set()
    for participant in await repos.offline_participants.list_confirmed_links(exam_id):
        participant_id = int(participant["participant_id"])
        user_id = int(participant.get("linked_user_id") or participant.get("matched_user_id") or 0)
        if not user_id:
            continue
        attempt = await repos.offline_attempts.get_for_participant(exam_id, participant_id)
        online = await repos.answers.get(user_id, exam_id)
        if attempt is not None and online is not None:
            linked_user_ids.add(user_id)
            active = await repos.offline_decisions.get_active(exam_id, "telegram_user", user_id)
            if active is None or int(active.get("included_in_ranking") or 1) != 0:
                await repos.offline_decisions.upsert(
                    exam_id=exam_id, subject_type="telegram_user", subject_id=user_id,
                    source="online", included=0, reason="offline_official_duplicate",
                )
        else:
            await repos.offline_decisions.deactivate(exam_id, "telegram_user", user_id)

    for decision in await repos.offline_decisions.list_active(exam_id, source="online"):
        if int(decision.get("subject_id") or 0) not in linked_user_ids:
            await repos.offline_decisions.deactivate(
                exam_id, "telegram_user", int(decision["subject_id"])
            )
    return len([
        d for d in await repos.offline_decisions.list_active(exam_id, source="online")
        if int(d.get("included_in_ranking") or 0) == 0
    ])


async def link_participant(
    repos: Repositories, *, participant_id: int, user_id: int,
    admin_id: int, method: str = "manual",
) -> None:
    """Admin tasdig'i bilan oflayn natijani Telegram profiliga bog'laydi."""
    participant = await repos.offline_participants.get(participant_id)
    if participant is None:
        raise OfflineImportError("Oflayn ishtirokchi topilmadi.")
    if await repos.users.get(user_id) is None:
        raise OfflineImportError("Telegram foydalanuvchisi topilmadi.")
    await repos.offline_participants.confirm_link(
        participant_id=participant_id, user_id=user_id,
        admin_id=admin_id, method=method,
    )
    await ensure_ranking_decisions(repos, int(participant["exam_id"]))
    await _audit(
        repos, admin_id=admin_id, action="offline.participant.link",
        entity_type="offline_participant", entity_id=participant_id,
        after={"user_id": user_id, "method": method},
    )


async def unlink_participant(repos: Repositories, *, participant_id: int, admin_id: int) -> None:
    """Bog'lanishni bekor qiladi; online natija reytingga qaytadi."""
    participant = await repos.offline_participants.get(participant_id)
    if participant is None:
        raise OfflineImportError("Oflayn ishtirokchi topilmadi.")
    await repos.offline_participants.revoke_link(participant_id, admin_id)
    await ensure_ranking_decisions(repos, int(participant["exam_id"]))
    await _audit(
        repos, admin_id=admin_id, action="offline.participant.unlink",
        entity_type="offline_participant", entity_id=participant_id,
    )
