"""Item qiyinchiligini (``b``) VAQTINCHA klassik statistikadan hisoblash.

Maqsad va chegaralar
--------------------
* Hozircha to'liq Rasch kalibrovkasi **qilinmaydi**; admin qo'lda ``b``
  kiritmaydi — test (sessiya) yopilgach bot **avtomatik** hisoblaydi:

      p = correct_count / N          # N = barcha qatnashchilar (bo'shlar ham!)
      p = clip(p, 0.01, 0.99)        # cheksiz `ln` dan qochish
      b = ln((1 - p) / p)
      b = clip(b, B_MIN, B_MAX)      # chegara: b ∈ [-4.6, +4.6] (oshmasligi kafolat)

* Chegara: ``b`` hech qachon ``±B_MAX`` (≈4.6) dan oshib ketmaydi. Chegaraga
  yetgan item (masalan **hech kim yechmagan** yoki **hamma yechgan**) ishonchsiz
  hisoblanadi va hisobotda ``⚠️ chegara`` bilan belgilanadi (:func:`is_at_limit`).
* Natija ``item_difficulty_stats`` jadvaliga yoziladi (006 migratsiya).
* **Barcha ``b`` hisoblash logikasi bitta joyda** —
  :func:`calculate_item_difficulty` va uni chaqiruvchi ``MODEL``. Kelajakda
  haqiqiy Rasch kalibrovkasiga o'tish uchun faqat ``MODEL`` ni almashtirish
  kifoya (:func:`set_model`), qolgan kod o'zgarmaydi.

Muhim qoida (maxraj)
--------------------
N = ``test topshirgan barcha o'quvchilar`` = ``correct + wrong + blank``.
Bo'sh qoldirilgan javoblar ham N ga **kiradi**:

    p = correct / N                    # TO'G'RI
    p = correct / (correct + wrong)    # NOTO'G'RI (blanksiz)

Manba (mavjud bazadan — o'zgartirilmagan)
-----------------------------------------
Javoblar item-level saqlanadi:
    1. ``responses`` — autosave logi (faqat tegib o'tilgan savollar);
    2. ``scoring_snapshot_items`` — baholashda MUZLATILGAN haqiqat: har bir
       urinish uchun har bir savol (bo'shlari ham) bitta satr; ``capture_status``
       ``answered`` / ``blank`` / ``not_reached``.

55 element = ``1``..``35`` (yopiq) + ``36a``..``45b`` (ochiq, A/B qismlari = 20).
``test_id`` = ``exam_sessions.session_id`` (bot oqimida "test" = sessiya).

Bu modul ``scoring.py`` / ``rasch.py`` / ``grading.py`` / ``analytics.py`` ga
**tegmaydi** — ular o'zgarmaydi.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Callable, Mapping, Protocol, Sequence

import config
from database.repository import Repositories

logger = logging.getLogger(__name__)

#: `p` shu chegaralarga siqiladi (`p=0` yoki `p=1` → `ln` cheksizligidan qochish).
CLIP_MIN: float = 0.01
CLIP_MAX: float = 0.99

#: `b` (logit) ning MUTLAQ chegarasi — natija hech qachon `[B_MIN, B_MAX]`
#: oralig'idan tashqariga chiqmaydi. Amalda `p` yuqoridagi `[CLIP_MIN, CLIP_MAX]`
#: ga siqilgani uchun eng katta `|b| ≈ 4.595` bo'ladi; bu chegara — qo'shimcha
#: kafolat va kelajakdagi (masalan Rasch) modellar uchun ham amal qiladi.
B_MAX: float = 4.6
B_MIN: float = -4.6

#: Shu tolerans ichida chegaraga yetgan `b` — 「chegarada」 (:func:`is_at_limit`)
#: deb belgilanadi. `p` siqilganda `b ≈ ±4.595`, ya'ni `4.6 - 0.01` dan yuqori.
LIMIT_EPS: float = 0.01

#: Shrinkaj konstantasi `K` (empirik Bayes). Yakuniy qiyinchilik o'qituvchi
#: bahosi va javob ma'lumoti o'rtasida `N` ga qarab aralashtiriladi:
#:
#:     w = N / (N + K)
#:     b = w · b_auto + (1 − w) · b_teacher
#:
#: `N = K` bo'lganda vaznlar teng (0.5). docs/01 va docs/02 dagi
#: `calibration.k_shrink = 30` bilan bir xil.
K_SHRINK: float = 30.0

#: Fon vazifasi oralig'i (sekund) — `config.ITEM_STATISTICS_INTERVAL` ustun.
DEFAULT_INTERVAL: int = 30

#: Hisobot bo'lagi maksimal uzunligi (Telegram 4096 belgi chegarasi uchun zaxira).
REPORT_CHUNK_CHARS: int = 3500


# ---------------------------------------------------------------------------
# 1) `b` ni hisoblashning YAGONA joyi (kelajakda shu yerni almashtiramiz)
# ---------------------------------------------------------------------------
def calculate_item_difficulty(
    correct_count: int, total_participants: int
) -> float | None:
    """Vaqtinchalik klassik qiyinchilik: ``p = correct/N`` → ``b = ln((1-p)/p)``.

    **Maxraj — ``total_participants`` (N)**, ya'ni ``correct + wrong + blank``.
    Bo'sh javoblar ham N ga kiradi; ``correct/(correct+wrong)`` **ishlatilmaydi**.

    ``p`` ``[CLIP_MIN, CLIP_MAX]`` oralig'iga siqiladi, so'ng natija ``b``
    ``[B_MIN, B_MAX]`` (≈ ±4.6) oralig'iga qat'iy to'g'rilanadi — ya'ni ``b``
    hech qachon chegaradan oshib ketmaydi.

    Args:
        correct_count: to'g'ri javob berganlar soni.
        total_participants: N — test topshirgan barcha o'quvchilar.

    Returns:
        ``b`` (logit, ``[B_MIN, B_MAX]`` ichida) yoki N = 0 bo'lsa ``None``.
    """
    n = int(total_participants)
    if n <= 0:
        return None
    p = int(correct_count) / n
    p = max(CLIP_MIN, min(CLIP_MAX, p))
    b = math.log((1.0 - p) / p)
    # Yakuniy chegara — `b` hech qachon ±B_MAX dan oshmaydi.
    return max(B_MIN, min(B_MAX, b))


def correct_fraction(
    correct_count: int, total_participants: int
) -> float | None:
    """Xom ulush ``p = correct / N`` (0..1, clip qilinmagan) — hisobot uchun."""
    n = int(total_participants)
    if n <= 0:
        return None
    return int(correct_count) / n


def is_at_limit(b_value: float | None) -> bool:
    """``b`` chegara hududiga yetganmi (ekstremal, ishonchsiz item)?

    ``b`` ning mutlaq qiymati ``B_MAX - LIMIT_EPS`` dan katta yoki teng bo'lsa
    ``True``. Bu asosan ikki holatda yuz beradi:

    * **hech kim yechmagan** savol (``p → 0``) → ``b ≈ +B_MAX`` (juda qiyin);
    * **hamma yechgan** savol (``p → 1``) → ``b ≈ -B_MAX`` (juda oson).

    Bunday itemning ``b`` qiymati ishonchsiz, shuning uchun hisobotda
    ``⚠️ chegara`` bilan ajratiladi (``_render_block``).

    Args:
        b_value: item qiyinchiligi (logit) yoki ``None``.

    Returns:
        ``True`` — chegarada; ``False`` — yo'q (yoki ``b_value is None``).
    """
    if b_value is None:
        return False
    return abs(float(b_value)) >= (B_MAX - LIMIT_EPS)


def shrinkage_weight(total_participants: int, k: float = K_SHRINK) -> float:
    """Ma'lumot (javob) vazni ``w = N / (N + K)`` — 0..1 oralig'ida.

    * ``N = 0``  → ``0.0`` (faqat o'qituvchi bahosi ishonchli);
    * ``N = K``  → ``0.5`` (teng vazn);
    * ``N → ∞``  → ``1.0`` (faqat javob ma'lumoti).

    Args:
        total_participants: ``N`` — shu savolni ishlaganlar soni.
        k: shrinkaj konstantasi (standart :data:`K_SHRINK`).

    Returns:
        ``w`` (0..1). ``k <= 0`` da ``N > 0`` bo'lsa ``1.0``, aks holda ``0.0``.
    """
    n = max(0, int(total_participants))
    kk = float(k)
    if kk <= 0.0:
        return 1.0 if n > 0 else 0.0
    return n / (n + kk)


def blend_difficulty(
    b_auto: float | None,
    b_teacher: float | None,
    total_participants: int,
    k: float = K_SHRINK,
) -> float | None:
    """Yakuniy qiyinchilik: ``b = w · b_auto + (1 − w) · b_teacher`` (shrinkaj).

    O'qituvchi bahosi (``b_teacher``) — kichik ``N`` uchun **tayanch** (prior);
    javob ma'lumoti (``b_auto``) — katta ``N`` uchun asosiy manba. Shuning uchun
    "o'quvchi kam bo'lsa — o'qituvchi, ko'p bo'lsa — avtomatik" talabi **o'zi**
    bajariladi (:func:`shrinkage_weight`), alohida tanlov shart emas.

    Args:
        b_auto: javoblardan chiqqan ``b`` (logit) yoki ``None``.
        b_teacher: o'qituvchi bahosidan chiqqan ``b`` (logit) yoki ``None``.
        total_participants: ``N`` — shu savolni ishlaganlar soni.
        k: shrinkaj konstantasi (standart :data:`K_SHRINK`).

    Returns:
        Aralashgan ``b`` (logit), yoki ikkalasi ham ``None`` bo'lsa ``None``:

        * ``b_teacher is None`` → ``b_auto`` (prior yo'q);
        * ``b_auto is None`` → ``b_teacher`` (ma'lumot yo'q, ``N = 0``);
        * ``w <= 0`` → ``b_teacher``; ``w >= 1`` → ``b_auto``.
    """
    if b_auto is None:
        return None if b_teacher is None else float(b_teacher)
    if b_teacher is None:
        return float(b_auto)
    w = shrinkage_weight(total_participants, k)
    if w <= 0.0:
        return float(b_teacher)
    if w >= 1.0:
        return float(b_auto)
    return w * float(b_auto) + (1.0 - w) * float(b_teacher)


def blended_b_map(
    counts: Mapping[str, tuple[int, int]],
    teacher_value: Callable[[str], float | None],
    k: float = K_SHRINK,
) -> dict[str, float]:
    """Har bir savol uchun yakuniy `b` (shrinkaj): `{kalit: b_final}`.

    Args:
        counts: `{kalit: (N, W)}` — shu savolni ishlaganlar (`N`) va to'g'ri
            javob berganlar (`W`) soni.
        teacher_value: kalit bo'yicha o'qituvchi `b` sini qaytaruvchi funksiya
            (topilmasa `None`).
        k: shrinkaj konstantasi (standart :data:`K_SHRINK`).

    Returns:
        `{kalit: b_final}` — faqat `N > 0` va hisoblangan qiymat `None`
        bo'lmagan kalitlar uchun.
    """
    result: dict[str, float] = {}
    for key, pair in counts.items():
        n, correct = int(pair[0]), int(pair[1])
        if n <= 0:
            continue
        b_auto = calculate_item_difficulty(correct, n)
        value = blend_difficulty(b_auto, teacher_value(str(key)), n, k)
        if value is not None:
            result[str(key)] = float(value)
    return result



# ---------------------------------------------------------------------------
# 2) Model interfeysi — kelajakdagi Rasch kalibrovkasiga o'tish nuqtasi
# ---------------------------------------------------------------------------
class DifficultyModel(Protocol):
    """Item qiyinchiligini baholovchi model (almashtiriladigan strategiya)."""

    #: Model nomi (loglar va kelajakdagi `item_parameters.source` uchun).
    name: str

    def estimate_item(
        self, correct_count: int, total_participants: int
    ) -> float | None:
        """Bitta item uchun ``b`` (logit)."""
        ...


class ClassicalLogitModel:
    """Hozirgi **VAQTINCHALIK** model: klassik ``p → b`` (kalibrovka emas)."""

    name = "classical_logit"

    def estimate_item(
        self, correct_count: int, total_participants: int
    ) -> float | None:
        """`calculate_item_difficulty()` ga topshiradi (yagona hisoblash nuqtasi)."""
        return calculate_item_difficulty(correct_count, total_participants)


#: Joriy model. Kelajakda: ``set_model(RaschJMLEModel())`` — boshqa kod o'zgarmaydi.
MODEL: DifficultyModel = ClassicalLogitModel()


def set_model(model: DifficultyModel) -> None:
    """Hisoblash modelini almashtiradi (Rasch kalibrovkaga o'tish nuqtasi).

    Misol (kelajakda)::

        class RaschJMLEModel:                 # barcha itemlarni birgalikda baholaydi
            name = "rasch_jmle"

            def calibrate(self, matrix): ...  # response matrix (u_ij)

            def estimate_item(self, correct_count, total_participants): ...

        set_model(RaschJMLEModel())

    Qolgan oqim (hisoblash, yozish, hisobot) o'zgarmaydi.
    """
    global MODEL
    MODEL = model
    logger.info("Item qiyinchilik modeli almashtirildi: %s", model.name)


# ---------------------------------------------------------------------------
# 3) Hisoblash va bazaga yozish
# ---------------------------------------------------------------------------
async def compute_item_statistics(
    repos: Repositories, test_id: int
) -> list[dict[str, Any]]:
    """Item statistikasini **hisoblaydi** (bazaga yozmaydi).

    Manba: ``scoring_snapshot_items`` + yakuniy (``is_final = 1``)
    ``scoring_snapshots``. N = ``correct + wrong + blank`` (bo'shlar kiradi).

    Args:
        repos: repository konteyneri.
        test_id: ``exam_sessions.session_id``.

    Returns:
        Har bir element uchun lug'at ro'yxati (item tartibida).
    """
    raw = await repos.item_difficulty.aggregate(test_id)
    rows: list[dict[str, Any]] = []
    for record in raw:
        correct = int(record["correct_count"] or 0)
        wrong = int(record["wrong_count"] or 0)
        blank = int(record["blank_count"] or 0)
        total = correct + wrong + blank  # N — bo'shlar ham ichida
        fraction = correct_fraction(correct, total)
        b_value = MODEL.estimate_item(correct, total)
        rows.append(
            {
                "test_id": int(test_id),
                "item_no": str(record["item_no"]),
                "total_participants": total,
                "correct_count": correct,
                "wrong_count": wrong,
                "blank_count": blank,
                "percent_correct": (
                    None if fraction is None else round(fraction * 100.0, 2)
                ),
                "b_value": b_value,
                # Hisobot/tekshiruv uchun qulaylik: chegara hududidami?
                "b_at_limit": is_at_limit(b_value),
            }
        )
    return rows


async def build_item_statistics(
    repos: Repositories, test_id: int
) -> list[dict[str, Any]]:
    """Test uchun item statistikasini hisoblab, ``item_difficulty_stats`` ga yozadi.

    **Idempotent:** avvalgi yozuvlar o'chiriladi va qaytadan yoziladi — shu sababli
    regrade (qayta baholash) ham to'g'ri yangilanadi.

    Args:
        repos: repository konteyneri.
        test_id: ``exam_sessions.session_id``.

    Returns:
        Saqlangan yozuvlar (item tartibida); ma'lumot bo'lmasa — bo'sh ro'yxat.
    """
    rows = await compute_item_statistics(repos, test_id)
    if not rows:
        logger.debug("Item statistika: test_id=%s uchun ma'lumot yo'q", test_id)
        return []
    await repos.item_difficulty.replace(test_id, rows)
    logger.info(
        "Item statistika yozildi: test_id=%s, elementlar=%d, N=%s",
        test_id,
        len(rows),
        rows[0]["total_participants"],
    )
    rows = await repos.item_difficulty.list_for_test(test_id)
    # Baholashda ISHLATILGAN `b` (`scoring_snapshot_items.b_used`) — hisobotni
    # baholash natijasi bilan izchil qilish uchun (`b` yonida `b_used`).
    used = await repos.item_difficulty.used_b_values(test_id)
    for row in rows:
        row["b_used"] = used.get(str(row["item_no"]))
    return rows

# ---------------------------------------------------------------------------
# 4) Admin hisoboti
# ---------------------------------------------------------------------------
def _render_block(row: dict[str, Any]) -> str:
    """Bitta element bloki (so'ralgan formatda).

    Chegaraga yetgan item (``b ≈ ±4.6``, ya'ni ``p`` siqilgan ekstremal holat)
    ``⚠️ chegara`` bilan belgilanadi — bunday baho ishonchsiz (ekstremal).

    Baholashda ishlatilgan ``b`` (``b_used``) mavjud bo'lsa, ``b`` yonida alohida
    satr sifatida ko'rsatiladi (natija bilan izchillik uchun).
    """
    percent = row.get("percent_correct")
    b_value = row.get("b_value")
    percent_text = "—" if percent is None else f"{float(percent):.1f}%"
    b_text = "—" if b_value is None else f"{float(b_value):.3f}"
    if is_at_limit(b_value):
        b_text = f"{b_text}  ⚠️ chegara"
    lines = [
        f"{row['item_no']}-savol",
        f"N={int(row['total_participants'])}",
        f"Correct={int(row['correct_count'])}",
        f"Wrong={int(row['wrong_count'])}",
        f"Blank={int(row['blank_count'])}",
        f"p={percent_text}",
        f"b={b_text}",
    ]
    b_used = row.get("b_used")
    if b_used is not None:
        lines.append(f"b_used={float(b_used):.3f}")
    return "\n".join(lines)


def render_admin_report(
    rows: Sequence[dict[str, Any]],
    *,
    title: str | None = None,
    chunk_chars: int = REPORT_CHUNK_CHARS,
) -> list[str]:
    """Admin uchun hisobotni tayyorlaydi (Telegram bo'laklariga bo'lingan).

    Format (har element uchun)::

        1-savol
        N=100
        Correct=22
        Wrong=45
        Blank=33
        p=22.0%
        b=1.266

    Returns:
        Xabar bo'laklari ro'yxati (har biri ``chunk_chars`` dan kichik).
    """
    if not rows:
        return ["Statistika mavjud emas."]

    header = f"📊 {title}\nElementlar: {len(rows)}\n\n" if title else ""
    chunks: list[str] = []
    current = header
    for row in rows:
        piece = _render_block(row) + "\n\n"
        if current.strip() and len(current) + len(piece) > chunk_chars:
            chunks.append(current.rstrip())
            current = ""
        current += piece
    if current.strip() or not chunks:
        chunks.append(current.rstrip())
    return chunks


# ---------------------------------------------------------------------------
# 5) Fon vazifasi — test yopilgach avtomatik hisoblash
# ---------------------------------------------------------------------------
async def statistics_loop(
    repos: Repositories, interval: int | None = None
) -> None:
    """Fon vazifasi: baholangan testlar uchun item statistikasini avtomatik yozadi.

    `main.py` da ``asyncio.create_task(...)`` orqali ishga tushiriladi va bot
    to'xtaganda ``task.cancel()`` bilan to'xtatiladi (``grading_loop`` bilan bir xil).
    """
    delay = int(
        interval
        if interval is not None
        else getattr(config, "ITEM_STATISTICS_INTERVAL", DEFAULT_INTERVAL)
    )
    logger.info("Item statistika fon vazifasi ishga tushdi (interval=%d s)", delay)
    while True:
        try:
            for test_id in await repos.item_difficulty.sessions_needing_stats():
                rows = await build_item_statistics(repos, int(test_id))
                if rows:
                    logger.info(
                        "Item statistika tayyor: test_id=%s, elementlar=%d",
                        test_id,
                        len(rows),
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - fon vazifasi baribir ishlayveradi
            logger.exception("Item statistika siklida kutilmagan xatolik")
        await asyncio.sleep(delay)


