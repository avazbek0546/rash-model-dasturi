"""O'quvchilar natijalari — **PDF hisobot** (faqat admin uchun).

Excelga o'xshash **rangli jadval**: har bir o'quvchi satri uning **darajasiga
qarab och fon rangi** bilan bo'yaladi (yozuv — qora). Ballar **yuqoridan pastga**
saralanadi. Hisobot **on-demand** yasaladi (saqlanmaydi) — admin uni bir marta
olib kanalga qo'yadi.

Shrift: lotin harflari uchun **Unicode TTF** kerak (`o'`, `g'` uchun). Shrift
**repoda birga keladi** — `assets/fonts/DejaVuSans.ttf` (birinchi nomzod), shu
tufayli PDF Windows'da ham, Linux (Railway) konteynerida ham bir xil ishlaydi.
Tizim shriftlari (Arial/Segoe UI/DejaVu/Noto) faqat **zaxira**: repodagi fayl
o'chirib yuborilgan holatda ham hisobot yasaladi. Railway build'ida
`nixpacks.toml` qo'shimcha ravishda `fonts-dejavu-core` paketini o'rnatadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import config

logger = logging.getLogger(__name__)

#: Shrift nomzodlari (birinchi topilgani ishlatiladi):
#: 1) repodagi DejaVuSans; 2) Windows; 3) Linux (Debian/Ubuntu, Arch, Nix);
#: 4) macOS. Shrift topilmasa — `ReportError` (jimgina buzuq PDF yasalmaydi).
FONT_CANDIDATES: tuple[Path, ...] = (
    config.BASE_DIR / "assets" / "fonts" / "DejaVuSans.ttf",
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/calibri.ttf"),
    Path("C:/Windows/Fonts/tahoma.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    Path("/run/current-system/sw/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
)

#: Daraja → och fon rangi (RGB). `NC` — rangsiz (oq).
LEVEL_COLORS: dict[str, tuple[int, int, int]] = {
    "A+": (200, 230, 201),  # och yashil
    "A": (187, 222, 251),  # och moviy
    "B+": (255, 249, 196),  # och sariq
    "B": (255, 224, 178),  # och olov (orange)
    "C+": (197, 202, 233),  # och siyoh (indigo)
    "C": (248, 187, 208),  # och pushti
}

#: Jadval sarlavhasi va ramka ranglari.
HEADER_BG: tuple[int, int, int] = (69, 90, 100)  # to'q kulrang-moviy
BORDER: tuple[int, int, int] = (176, 190, 197)
WHITE: tuple[int, int, int] = (255, 255, 255)
BLACK: tuple[int, int, int] = (0, 0, 0)

#: Daraja tartibi (diagramma va izohlar uchun) — yuqoridan pastga.
LEVEL_ORDER: tuple[str, ...] = ("A+", "A", "B+", "B", "C+", "C", "NC")


class ReportError(RuntimeError):
    """PDF hisobotni yasashdagi xatolik (foydalanuvchiga ko'rsatiladi)."""


@dataclass(frozen=True, slots=True)
class StudentRow:
    """PDF jadvalidagi bitta o'quvchi satri."""

    name: str
    total_ball: float | None  # umumiy (sertifikat) bali — 0..100 shkala
    theta: float  # θ (logit) — Rasch modelining yagona o'lchovi
    level: str  # A+ / A / B+ / B / C+ / C / NC
    algebra: float | None  # algebra bo'limi balli
    geometry: float | None  # geometriya bo'limi balli
    correct: int  # to'g'ri javoblar soni
    total: int  # jami savol (element) soni


@lru_cache(maxsize=1)
def resolve_font() -> Path:
    """Lotinni qo'llovchi TTF shriftni topadi (natija **keshlanadi**).

    Birinchi navbatda repodagi `assets/fonts/DejaVuSans.ttf` tekshiriladi —
    shu tufayli hisobot barcha OS'larda (Windows / Linux / macOS) bir xil
    yasaladi. Topilmasa — tizim shriftlari (`FONT_CANDIDATES`) izlanadi.

    Eslatma: `lru_cache` faqat **muvaffaqiyatli** natijani keshlaydi; shrift
    keyinroq qo'shilsa, xato takrorlanmaydi.

    Raises:
        ReportError: shrift topilmasa (PDF yasab bo'lmaydi).
    """
    for path in FONT_CANDIDATES:
        try:
            if path.is_file():
                return path
        except OSError:  # ruxsat yo'q / buzuq yo'l — keyingi nomzodga o'tamiz
            continue
    raise ReportError(
        "PDF uchun Unicode shrift topilmadi. "
        "'assets/fonts/DejaVuSans.ttf' faylini loyihaga qo'shing "
        "(Linux/Railway'da 'fonts-dejavu-core' paketi ham yordam beradi)."
    )


#: Jadval ustunlari: `(sarlavha, eni_mm, tekislash)` — jami 190 mm (A4).
#: «Umumiy ball» — asosiy ko'rsatkich (0..100 sertifikat bali), shu sababli
#: ism-familiyadan keyin turadi; algebra + geometriya yig'indisi shu ballga teng.
COLUMNS: tuple[tuple[str, float, str], ...] = (
    ("#", 9, "C"),
    ("Ism-familiya", 58, "L"),
    ("Umumiy ball", 24, "C"),
    ("Algebra", 20, "C"),
    ("Geometriya", 21, "C"),
    ("θ (logit)", 20, "C"),
    ("Daraja", 18, "C"),
    ("To'g'ri", 20, "C"),
)


def _fpdf():
    """`FPDF` obyektini yasaydi va Unicode shriftni o'rnatadi."""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_font(family="main", fname=str(resolve_font()))
    pdf.set_margins(10, 12, 10)
    pdf.set_auto_page_break(auto=True, margin=15)
    return pdf


def _text(pdf, height: float, text: str, *, size: int = 10, align: str = "L") -> None:
    """Bitta qator matn yozadi va pastga o'tadi."""
    pdf.set_font("main", size=size)
    pdf.cell(0, height, text=text, align=align)
    pdf.ln(height)


def _fmt(value: float | None) -> str:
    """Sonni ko'rsatish (bo'sh bo'lsa — `—`)."""
    return "—" if value is None else f"{float(value):.1f}"


def _level_counts(students: list[StudentRow]) -> dict[str, int]:
    """Daraja → o'quvchilar soni."""
    counts = {level: 0 for level in LEVEL_ORDER}
    for row in students:
        if row.level in counts:
            counts[row.level] += 1
    return counts


def _draw_chart(pdf, counts: dict[str, int]) -> None:
    """Daraja taqsimoti — gorizontal ustunli diagramma (fpdf chizmalari bilan)."""
    pdf.set_text_color(*BLACK)
    _text(pdf, 8, "Daraja taqsimoti", size=12)
    total = sum(counts.values())
    if total == 0:
        _text(pdf, 6, "Ma'lumot yo'q.", size=9)
        pdf.ln(2)
        return

    label_w = 14.0
    bar_w = 120.0
    row_h = 6.5
    for level in LEVEL_ORDER:
        count = counts.get(level, 0)
        pdf.set_font("main", size=9)
        pdf.set_text_color(*BLACK)
        pdf.cell(label_w, row_h, text=level, align="L")
        x = pdf.get_x()
        y = pdf.get_y()
        width = bar_w * count / total
        pdf.set_fill_color(*LEVEL_COLORS.get(level, (230, 230, 230)))
        pdf.set_draw_color(*BORDER)
        pdf.rect(x, y + 1.0, max(width, 0.4), row_h - 2.0, style="DF")
        pdf.set_x(x + bar_w + 2.0)
        pdf.cell(30, row_h, text=f"{count} ta", align="L")
        pdf.ln(row_h)
    pdf.ln(2)


def _draw_header(pdf, *, title: str, test_code: str, date_text: str, participants: int) -> None:
    """Sarlavha bloki."""
    pdf.set_text_color(*BLACK)
    _text(pdf, 9, "RASH EXAM — NATIJALAR", size=16, align="C")
    _text(pdf, 7, str(title), size=12, align="C")
    _text(
        pdf,
        6,
        f"Kod: {test_code}   ·   Sana: {date_text}   ·   Qatnashgan: {participants}",
        size=10,
        align="C",
    )
    pdf.ln(2)


def build_results_pdf(
    *,
    title: str,
    test_code: str,
    date_text: str,
    participants: int,
    students: list[StudentRow],
) -> bytes:
    """O'quvchilar natijalari PDF ini yasaydi va **baytlarini** qaytaradi.

    `students` allaqachon ball bo'yicha **kamayish tartibida** saralangan bo'lishi
    kerak. Hisobot saqlanmaydi — har so'ralganda yasaladi.

    Raises:
        ReportError: shrift topilmasa.
    """
    pdf = _fpdf()
    pdf.add_page()
    _draw_header(
        pdf,
        title=title,
        test_code=test_code,
        date_text=date_text,
        participants=participants,
    )
    _draw_chart(pdf, _level_counts(students))

    pdf.set_text_color(*BLACK)
    _text(pdf, 8, "O'quvchilar natijalari", size=12)

    # Jadval sarlavhasi (to'q fon, oq yozuv)
    pdf.set_font("main", size=9)
    pdf.set_fill_color(*HEADER_BG)
    pdf.set_text_color(*WHITE)
    pdf.set_draw_color(*BORDER)
    for heading, width, align in COLUMNS:
        pdf.cell(width, 7, text=heading, border=1, align=align, fill=True)
    pdf.ln(7)

    # Satrlar (daraja rangida)
    for index, row in enumerate(students, start=1):
        color = LEVEL_COLORS.get(row.level)  # NC → None → rangsiz
        pdf.set_fill_color(*(color or WHITE))
        pdf.set_text_color(*BLACK)
        pdf.set_font("main", size=9)
        pdf.set_draw_color(*BORDER)
        values = (
            str(index),
            str(row.name),
            _fmt(row.total_ball),
            _fmt(row.algebra),
            _fmt(row.geometry),
            f"{row.theta:+.2f}",
            str(row.level),
            f"{row.correct}/{row.total}",
        )
        for (_heading, width, align), value in zip(COLUMNS, values):
            pdf.cell(width, 6.5, text=value, border=1, align=align, fill=color is not None)
        pdf.ln(6.5)

    if not students:
        pdf.set_text_color(*BLACK)
        _text(pdf, 6, "Hozircha natija yo'q.", size=9)

    return bytes(pdf.output())
