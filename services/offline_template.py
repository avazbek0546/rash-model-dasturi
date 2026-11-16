"""Offline mock uchun Excel shablon generatori.

Shablon imtihonning **joriy formasi** dan yaratiladi: 55 ta ustun aynan
`form_items.display_label` tartibida bo'ladi. O'qituvchi ustunlarni qo'lda
tuzmaydi — shu bilan `36a`/`36b` tartibi va kalit versiyasi chalkashmaydi.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

import config
from database.models import Exam
from services.offline_scoring import OfflineReadiness

logger = logging.getLogger(__name__)

SHEET_RESULTS = "Natijalar"
SHEET_META = "Meta"
SHEET_HELP = "Ko'rsatma"

HEADER_FILL = PatternFill("solid", fgColor="455A64")
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN = Side(style="thin", color="B0BEC5")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

BASE_HEADERS: tuple[str, ...] = (
    "student_code",
    "full_name",
    "class",
    "telegram_username",
)


def build_template(exam: Exam, readiness: OfflineReadiness) -> bytes:
    """Imtihonga bog'langan `.xlsx` shablonni qaytaradi."""
    if not readiness.ready:
        raise ValueError(readiness.reason)

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_RESULTS
    headers = list(BASE_HEADERS) + list(readiness.labels)
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = BORDER
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 34

    widths = {
        "A": 16, "B": 30, "C": 10, "D": 20,
    }
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    for index in range(len(BASE_HEADERS) + 1, len(headers) + 1):
        letter = ws.cell(row=1, column=index).column_letter
        ws.column_dimensions[letter].width = 7

    max_rows = max(100, min(int(config.OFFLINE_IMPORT_MAX_ROWS), 2000))
    validation = DataValidation(type="list", formula1='"0,1"', allow_blank=False)
    validation.error = "Faqat 0 yoki 1 kiriting."
    validation.errorTitle = "Noto'g'ri qiymat"
    validation.prompt = "1 — to'g'ri, 0 — noto'g'ri"
    validation.promptTitle = "Javob"
    ws.add_data_validation(validation)
    first_col = len(BASE_HEADERS) + 1
    last_col = len(headers)
    # Bitta oraliq sifatida qo'shamiz — katakma-katak qo'shish juda sekin.
    from openpyxl.utils import get_column_letter

    validation.add(
        f"{get_column_letter(first_col)}2:{get_column_letter(last_col)}{max_rows + 1}"
    )

    meta = wb.create_sheet(SHEET_META)
    meta_rows = [
        ("template_version", str(config.OFFLINE_TEMPLATE_VERSION)),
        ("exam_id", str(exam.exam_id)),
        ("test_code", str(exam.test_code)),
        ("form_version_id", str(readiness.form_version_id or "")),
        ("total_items", str(len(readiness.labels))),
        ("labels_order_hash", readiness.labels_order_hash),
        ("key_fingerprint", readiness.key_fingerprint),
        ("b_checksum", readiness.b_checksum),
        ("b_source", readiness.b_source),
        ("engine_version", readiness.engine_version),
        ("generated_at", ""),
        ("generated_by", ""),
    ]
    meta.append(["key", "value"])
    for key, value in meta_rows:
        meta.append([key, value])
    for cell in meta[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    meta.column_dimensions["A"].width = 24
    meta.column_dimensions["B"].width = 80

    help_ws = wb.create_sheet(SHEET_HELP)
    help_lines = [
        "OFFLINE MOCK — TO'LDIRISH QOIDALARI",
        "",
        "1. `Natijalar` varag'ida faqat sariq/kulrang sarlavhali ustunlarni to'ldiring.",
        "2. `student_code` — o'quvchining jurnal raqami (imtihon ichida takrorlanmasin).",
        "3. `full_name` — ism-familiya; `class` — sinf/guruh.",
        "4. `telegram_username` — ixtiyoriy; aniq moslik uchun.",
        "5. Har bir topshiriq uchun faqat 0 yoki 1: 1 — to'g'ri, 0 — noto'g'ri.",
        "6. 55 ta ustun: 1–35, 36a, 36b, …, 45a, 45b. Tartibni o'zgartirmang.",
        "7. Bo'sh katak qoldirmang; formula ishlatmang; qatorlarni birlashtirmang.",
        "8. Faylni `.xlsx` ko'rinishida saqlang (`.xls` yoki `.xlsm` emas).",
        "",
        "Bu shablon imtihonning kaliti va `b` parametrlariga bog'langan. "
        "Boshqa test uchun qayta yaratiladi.",
    ]
    for line in help_lines:
        help_ws.append([line])
    help_ws.column_dimensions["A"].width = 110

    buffer = io.BytesIO()
    wb.save(buffer)
    logger.info(
        "Offline shablon yaratildi: exam_id=%s, items=%d, bytes=%d",
        exam.exam_id,
        len(readiness.labels),
        len(buffer.getvalue()),
    )
    return buffer.getvalue()


def template_filename(exam: Exam) -> str:
    """Yuklab olinadigan fayl nomi."""
    return f"mock-{exam.test_code}-offline-shablon.xlsx"


def template_meta(readiness: OfflineReadiness, exam: Exam) -> dict[str, Any]:
    """Shablon metadatasini qaytaradi (test/debug uchun)."""
    return {
        "test_code": exam.test_code,
        "exam_id": exam.exam_id,
        "form_version_id": readiness.form_version_id,
        "total_items": len(readiness.labels),
        "labels_order_hash": readiness.labels_order_hash,
        "key_fingerprint": readiness.key_fingerprint,
        "b_checksum": readiness.b_checksum,
        "b_source": readiness.b_source,
        "engine_version": readiness.engine_version,
    }
