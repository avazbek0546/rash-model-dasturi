"""Rasch modeli (1PL IRT) asosida o'quvchining bilim darajasini baholash.

Nazariy asos
------------
Har bir o'quvchining yashirin "bilim darajasi" θ (theta, logit) va har bir
savolning yashirin "qiyinchiligi" b (logit) mavjud. O'quvchi j-savolga
to'g'ri javob berish ehtimoli (dichotomous Rasch modeli):

    P_j(θ) = 1 / (1 + exp(-(θ - b_j)))

Ya'ni:
  * θ = b_j  → to'g'ri javob berish ehtimoli 0.5;
  * θ >> b_j → ehtimol 1 ga yaqin (savol o'quvchi uchun oson);
  * θ << b_j → ehtimol 0 ga yaqin (savol o'quvchi uchun qiyin).

Nega shunchaki "to'g'ri javoblar soni" yetarli emas?
---------------------------------------------------
Rasch modelida xom ball (raw score) — savollar to'plami aniq belgilangan
bo'lsa — θ uchun "yetarli statistika" (sufficient statistic) hisoblanadi.
Ya'ni bir xil 10 ta savolga bir xil sonda to'g'ri javob bergan ikki
o'quvchi bir xil θ oladi. Farq mana shunda ko'rinadi:

    * 20 savollik bazadan OSON 10 tasi tanlansa, 5/10 natija θ ≈ -1.6;
    * o'sha bazadan QIYIN 10 tasi tanlansa, xuddi shu 5/10 natija θ ≈ +1.4.

Demak "5/10" degan yozuvning ma'nosi savollar qiyinligiga qarab butunlay
boshqacha bo'ladi. Rasch modeli aynan shu taqqoslashni to'g'ri bajaradi va
har bir bahoning aniqligini standart xato (SE) hamda 95% ishonch oralig'i
orqali ko'rsatib beradi — oddiy "7/10 = 70%" baholashda esa bu ma'lumot
yo'qolib ketadi.

Shu bilan birga, test ichida ham qiyinchilik muhim: har bir savolga to'g'ri
javob berish ehtimoli P_j(θ) savolning b_j qiymatiga bog'liq, shuning uchun
hisobotda "bu savolni sizning darajangizda yechish ehtimoli" ham
ko'rsatiladi.

θ qanday topiladi (MLE + Newton-Raphson)?
----------------------------------------
u_j ∈ {0, 1} — javob (1 = to'g'ri, 0 = noto'g'ri).

    L(θ)      = Π P_j^(u_j) · (1 - P_j)^(1 - u_j)          (likelihood)
    ln L(θ)   = Σ [u_j·ln P_j + (1 - u_j)·ln(1 - P_j)]
    ln L'(θ)  = Σ (u_j - P_j)                               (1-hosila)
    ln L''(θ) = -Σ P_j·(1 - P_j) = -I(θ)                    (2-hosila)

Bu yerda I(θ) = Σ P_j(1 - P_j) — Fisher informatsiyasi. Shu sababli
Newton-Raphson iteratsiyasi juda sodda ko'rinishga ega:

    θ_(k+1) = θ_k + [Σ (u_j - P_j)] / [Σ P_j(1 - P_j)]

Standart xato (o'lchov aniqligi):  SE(θ) = 1 / sqrt(Σ P_j(1 - P_j)).

Chekka holatlar
---------------
Barcha javob to'g'ri yoki barchasi noto'g'ri bo'lsa MLE cheksizlikka
intiladi (SE ham cheksiz). Bunday holatda θ = ±THETA_BOUND qilib olinadi va
`is_extreme=True`, `standard_error=None` bo'ladi. Bu matematik cheklov,
xatolik emas — buni o'quvchiga izohlab ko'rsatamiz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import config
from database.models import SKIPPED, Question

EPS = 1e-12


@dataclass(slots=True)
class ItemResponse:
    """Bitta savolga berilgan javob (Rasch uchun minimal ma'lumot)."""

    question_id: int
    difficulty: float  # b_j (logit)
    is_correct: bool  # u_j (1 yoki 0)
    skipped: bool = False  # o'quvchi "Bilmayman" tugmasini bosgan


@dataclass(slots=True)
class RaschEstimate:
    """Rasch modeli bo'yicha to'liq baho natijasi."""

    theta: float  # θ (logit)
    standard_error: float | None  # SE(θ), chekka holatda None
    scaled_score: float  # 0..100 standart shkala
    raw_score: int  # to'g'ri javoblar soni
    total_items: int  # savollar soni
    log_likelihood: float  # ln L(θ), topilgan θ da
    iterations: int  # Newton-Raphson qadamlari soni
    converged: bool  # yechim yaqinlashdimi
    is_extreme: bool  # barchasi to'g'ri / barchasi noto'g'ri holati

    @property
    def correct_ratio(self) -> float:
        """To'g'ri javoblar ulushi (0..1)."""
        return self.raw_score / self.total_items if self.total_items else 0.0

    @property
    def theta_interval(self) -> tuple[float, float] | None:
        """95% ishonch oralig'i θ uchun (SE mavjud bo'lsa)."""
        if self.standard_error is None:
            return None
        delta = 1.96 * self.standard_error
        return (self.theta - delta, self.theta + delta)

    @property
    def scaled_error(self) -> float | None:
        """SE ning 0..100 shkaladagi ko'rinishi (ball bilan bir o'lchovda)."""
        if self.standard_error is None:
            return None
        return self.standard_error * config.scaled_span()

    @property
    def scaled_interval(self) -> tuple[float, float] | None:
        """95% ishonch oralig'ining 0..100 shkaladagi ko'rinishi."""
        interval = self.theta_interval
        if interval is None:
            return None
        low, high = interval
        return (theta_to_scaled(low), theta_to_scaled(high))


# ---------------------------------------------------------------------------
# Modelning asosiy funksiyalari
# ---------------------------------------------------------------------------
def probability(theta: float, difficulty: float) -> float:
    """P_j(θ) — logistik funksiya (to'g'ri javob ehtimoli).

    Barqarorlik uchun ikkita shoxobchadan foydalanamiz: katta musbat x da
    exp(-x) → 0, katta manfiy x da exp(x) → 0, shu sababli OverflowError
    yuzaga kelmaydi.
    """
    x = theta - difficulty
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def _safe_log(value: float) -> float:
    """log(0) → -inf o'rniga chekli katta manfiy son qaytaradi."""
    return math.log(value if value > EPS else EPS)


def log_likelihood(theta: float, responses: Sequence[ItemResponse]) -> float:
    """ln L(θ) = Σ [u_j·ln P_j + (1-u_j)·ln(1-P_j)]."""
    total = 0.0
    for item in responses:
        p = probability(theta, item.difficulty)
        total += _safe_log(p) if item.is_correct else _safe_log(1.0 - p)
    return total


def gradient(theta: float, responses: Sequence[ItemResponse]) -> float:
    """ln L'(θ) = Σ (u_j - P_j)."""
    return sum(
        (1.0 if item.is_correct else 0.0) - probability(theta, item.difficulty)
        for item in responses
    )


def information(theta: float, responses: Sequence[ItemResponse]) -> float:
    """I(θ) = Σ P_j(1 - P_j) — test shu θ da qanchalik aniq o'lchaydi."""
    total = 0.0
    for item in responses:
        p = probability(theta, item.difficulty)
        total += p * (1.0 - p)
    return total


def expected_score(theta: float, responses: Sequence[ItemResponse]) -> float:
    """Berilgan θ da nazariy kutilgan to'g'ri javoblar soni: Σ P_j(θ)."""
    return sum(probability(theta, item.difficulty) for item in responses)


def response_probabilities(
    theta: float, responses: Sequence[ItemResponse]
) -> list[float]:
    """Har bir savolga to'g'ri javob berish ehtimoli (hisobot uchun)."""
    return [probability(theta, item.difficulty) for item in responses]


# ---------------------------------------------------------------------------
# θ ni baholash (MLE / Newton-Raphson)
# ---------------------------------------------------------------------------
def _clip(value: float, lower: float, upper: float) -> float:
    """Qiymatni [lower, upper] oralig'iga siqadi."""
    return max(lower, min(upper, value))


def _empirical_start(raw_score: int, total_items: int, fallback: float) -> float:
    """Boshlang'ich θ: xom ballga mos logit (0 va 1 ni chetlab o'tib).

    θ_0 = ln[(u + 0.5) / (n - u + 0.5)] — bu "xom ball logit"i bo'lib,
    odatda haqiqiy MLE ga juda yaqin, shuning uchun iteratsiya tez yaqinlashadi.
    """
    if total_items <= 0:
        return fallback
    return math.log((raw_score + 0.5) / (total_items - raw_score + 0.5))


def estimate_theta(
    responses: Sequence[ItemResponse],
    *,
    bound: float | None = None,
    start: float | None = None,
    max_iter: int | None = None,
    tolerance: float | None = None,
) -> RaschEstimate:
    """Javoblar bo'yicha θ ni maksimal ishonchlilik (MLE) usulida baholaydi.

    Parametrlar:
        responses : ItemResponse ro'yxati (har birida b_j va u_j).
        bound     : θ qidiruv chegarasi (default: config.THETA_BOUND).
        start     : Newton-Raphson boshlang'ich nuqtasi.
        max_iter  : maksimal iteratsiya soni.
        tolerance : yaqinlashish aniqligi (|θ_(k+1) - θ_k| uchun).
    """
    items = list(responses)
    if not items:
        raise ValueError("estimate_theta(): kamida bitta ItemResponse kerak")

    limit = abs(float(config.THETA_BOUND if bound is None else bound))
    iterations_limit = int(config.MLE_MAX_ITER if max_iter is None else max_iter)
    tol = float(config.MLE_TOLERANCE if tolerance is None else tolerance)

    raw_score = sum(1 for item in items if item.is_correct)
    total_items = len(items)

    # 1) Chekka holat: MLE mavjud emas (barchasi to'g'ri yoki barchasi xato)
    if raw_score == 0 or raw_score == total_items:
        theta = float(limit if raw_score == total_items else -limit)
        return RaschEstimate(
            theta=theta,
            standard_error=None,
            scaled_score=theta_to_scaled(theta, -limit, limit),
            raw_score=raw_score,
            total_items=total_items,
            log_likelihood=log_likelihood(theta, items),
            iterations=0,
            converged=False,
            is_extreme=True,
        )

    # 2) Newton-Raphson: θ_(k+1) = θ_k + ln L'(θ_k) / I(θ_k)
    theta = float(config.MLE_START if start is None else start)
    if start is None:
        theta = _empirical_start(raw_score, total_items, config.MLE_START)

    iterations = 0
    converged = False
    current_ll = log_likelihood(theta, items)

    for step in range(1, iterations_limit + 1):
        iterations = step
        info = information(theta, items)
        if info <= EPS:  # informatsiya yo'q — davom etishning ma'nosi yo'q
            break

        delta = gradient(theta, items) / info
        candidate = _clip(theta + delta, -limit, limit)
        candidate_ll = log_likelihood(candidate, items)

        # Qadam log-likelihood'ni kamaytirsa — qadamni ikki barobar kichraytiramiz
        attempts = 0
        while candidate_ll < current_ll - 1e-9 and attempts < 10:
            delta /= 2.0
            candidate = _clip(theta + delta, -limit, limit)
            candidate_ll = log_likelihood(candidate, items)
            attempts += 1

        step_size = abs(candidate - theta)
        theta, current_ll = candidate, candidate_ll

        if step_size < tol:
            converged = True
            break

    info = information(theta, items)
    standard_error = (1.0 / math.sqrt(info)) if info > EPS else None

    # θ qidiruv chegarasiga urilib qolgan bo'lsa (masalan 11/12 to'g'ri javob),
    # haqiqiy MLE chegaradan tashqarida yotadi: gradient hali ham nolga teng
    # emas. Bunday baho "chegaraviy" deb belgilanadi.
    at_bound = abs(theta) >= limit - 1e-9
    boundary_gradient = gradient(theta, items)
    is_extreme = at_bound and abs(boundary_gradient) > 1e-4

    return RaschEstimate(
        theta=theta,
        standard_error=standard_error,
        scaled_score=theta_to_scaled(theta, -limit, limit),
        raw_score=raw_score,
        total_items=total_items,
        log_likelihood=current_ll,
        iterations=iterations,
        converged=converged,
        is_extreme=is_extreme,
    )


def evaluate(
    questions: Sequence[Question],
    answers: Mapping[int, str],
    **kwargs: float,
) -> RaschEstimate:
    """Savollar + o'quvchi javoblari bo'yicha to'liq Rasch bahosi."""
    return estimate_theta(build_responses(questions, answers), **kwargs)


# ---------------------------------------------------------------------------
# θ → 0..100 standart shkala (Scaled Score)
# ---------------------------------------------------------------------------
def theta_to_scaled(
    theta: float,
    theta_min: float | None = None,
    theta_max: float | None = None,
) -> float:
    """θ (logit) ni 0..100 shkalaga chiziqli o'tkazadi.

    Standart holat:  θ = -THETA_BOUND → 0 ball,  θ = 0 → 50 ball,
                     θ = +THETA_BOUND → 100 ball.

    Chiziqli o'tkazish:
        ball = 100 · (θ - θ_min) / (θ_max - θ_min)

    Natija avval ``[0, 100]`` ga, so'ng ``[SCALED_CAP_MIN, SCALED_CAP_MAX]``
    (masalan ``[9, 91]``) ga **qisiladi** — 0 va 100 ko'rinmasligi uchun
    (ishonchlilik). Oddiy ballar tegilmaydi, faqat eng chet qiymatlar.
    """
    low = -config.THETA_BOUND if theta_min is None else float(theta_min)
    high = config.THETA_BOUND if theta_max is None else float(theta_max)
    if high <= low:
        raise ValueError("theta_max theta_min dan katta bo'lishi kerak")

    span = config.SCALED_MAX - config.SCALED_MIN
    scaled = config.SCALED_MIN + (theta - low) * span / (high - low)
    bounded = _clip(scaled, config.SCALED_MIN, config.SCALED_MAX)
    return _clip(bounded, config.SCALED_CAP_MIN, config.SCALED_CAP_MAX)


def scaled_to_theta(
    scaled_score: float,
    theta_min: float | None = None,
    theta_max: float | None = None,
) -> float:
    """0..100 shkaladagi ballni θ (logit) ga qaytaradi (teskari o'tkazish)."""
    low = -config.THETA_BOUND if theta_min is None else float(theta_min)
    high = config.THETA_BOUND if theta_max is None else float(theta_max)
    span = config.SCALED_MAX - config.SCALED_MIN
    return low + (scaled_score - config.SCALED_MIN) * (high - low) / span


# ---------------------------------------------------------------------------
# Izoh (interpretatsiya) yordamchilari
# ---------------------------------------------------------------------------
def difficulty_label(difficulty: float) -> str:
    """Savol qiyinchiligini so'z bilan ifodalaydi."""
    if difficulty <= -1.5:
        return "juda oson"
    if difficulty <= -0.5:
        return "oson"
    if difficulty < 0.5:
        return "o'rtacha"
    if difficulty < 1.5:
        return "qiyin"
    return "juda qiyin"


#: Milliy sertifikat darajalari: `(pastki chegara, kod, tavsiya)` — pastdan yuqoriga.
#: Chegaralar INKLYUZIV (`,,>=`` ): `46.0 → C`, `70.0 → A+`. `< 46 → NC`
#: (sertifikat olinmadi).
CERTIFICATE_LEVELS: tuple[tuple[float, str, str], ...] = (
    (
        0.0,
        "NC",
        "Afsus, sertifikat olinmadi (NC). Asosiy mavzularni mustahkamlab, "
        "qayta urinib ko'ring.",
    ),
    (
        46.0,
        "C",
        "Sertifikat C darajasi. Oson va o'rtacha savollardagi xatolarni tuzatsangiz, "
        "natija oshadi.",
    ),
    (
        50.0,
        "C+",
        "Sertifikat C+ darajasi. Barqarorlikni oshirib, B darajaga chiqish mumkin.",
    ),
    (
        55.0,
        "B",
        "Sertifikat B darajasi. Qiyinroq savollar (trigonometriya, progressiyalar) "
        "ustida ishlang.",
    ),
    (
        60.0,
        "B+",
        "Sertifikat B+ darajasi. Qiyin savollarda aniqlikni oshiring — A daraja yaqin.",
    ),
    (
        65.0,
        "A",
        "Sertifikat A darajasi. Faqat eng qiyin savollarda xatolar qoldi.",
    ),
    (
        70.0,
        "A+",
        "Sertifikat A+ darajasi! Endi olimpiada tipidagi noan'anaviy masalalarga "
        "o'tish mumkin.",
    ),
)


def level_code(scaled_score: float) -> str:
    """0..100 ball bo'yicha **sertifikat darajasi kodi**.

    Chegaralar (pastdan yuqoriga, inklyuziv)::

        < 46    → NC   (sertifikat olinmadi)
        46–49.9 → C
        50–54.9 → C+
        55–59.9 → B
        60–64.9 → B+
        65–69.9 → A
        >= 70   → A+
    """
    score = float(scaled_score)
    code = CERTIFICATE_LEVELS[0][1]
    for threshold, level, _advice in CERTIFICATE_LEVELS:
        if score < threshold:
            break
        code = level
    return code


def ability_level(scaled_score: float) -> str:
    """O'quvchi darajasi (sertifikat kodi) — :func:`level_code` bilan bir xil."""
    return level_code(scaled_score)


def level_advice(scaled_score: float) -> str:
    """O'quvchiga qisqa tavsiya (daraja bo'yicha; natija izohida ko'rsatiladi)."""
    score = float(scaled_score)
    advice = CERTIFICATE_LEVELS[0][2]
    for threshold, _level, text in CERTIFICATE_LEVELS:
        if score < threshold:
            break
        advice = text
    return advice


def build_responses(
    questions: Sequence[Question],
    answers: Mapping[int, str],
) -> list[ItemResponse]:
    """Savollar va javoblar lug'atini `ItemResponse` ro'yxatiga aylantiradi.

    `answers` — {question_id: "A"/"B"/"C"/"D"/"X"}, bu yerda "X" = bilmayman.
    Javob berilmagan savol ham noto'g'ri (u_j = 0) deb hisoblanadi.

    Eslatma: bu funksiya eski "mashq rejimi" (savollar matni bazada) uchun;
    yangi imtihon platformasi `responses_from_letters()` dan foydalanadi.
    """
    responses: list[ItemResponse] = []
    for question in questions:
        answer = answers.get(question.question_id)
        responses.append(
            ItemResponse(
                question_id=question.question_id,
                difficulty=question.difficulty_b,
                is_correct=question.is_correct(answer),
                skipped=answer is None or answer.upper() == SKIPPED,
            )
        )
    return responses


def responses_from_letters(
    difficulties: Sequence[float],
    correct_letters: Sequence[str],
    given_letters: Sequence[str],
    *,
    skipped_letter: str = SKIPPED,
) -> list[ItemResponse]:
    """Logitlar + kalit + o'quvchi javoblari asosida `ItemResponse` ro'yxatini quradi.

    Bu funksiya yangi imtihon platformasi uchun ishlatiladi: savollar matni
    bazada saqlanmaydi, faqat ularning `b_j` (logit) qiymatlari va kalit
    harflari ma'lum. Bunda `question_id` sifatida savolning tartib raqami
    (1 dan boshlab) olinadi.

    Args:
        difficulties: har bir savolning qiyinchiligi (logit), masalan [0.0, 1.2, -0.5].
        correct_letters: kalit harflari, masalan ["A", "B", "C"].
        given_letters: o'quvchi javoblari, yetishmaganlari "X" (SKIPPED).
        skipped_letter: "javob berilmagan" belgisi (standart — "X").

    Raises:
        ValueError: ro'yxatlar uzunligi mos kelmasa yoki bo'sh bo'lsa.
    """
    if not difficulties:
        raise ValueError("Kamida bitta savol (logit) bo'lishi kerak.")
    if not (len(difficulties) == len(correct_letters) == len(given_letters)):
        raise ValueError(
            "Logitlar, kalit va javoblar soni teng bo'lishi kerak: "
            f"{len(difficulties)} ≠ {len(correct_letters)} ≠ {len(given_letters)}."
        )

    responses: list[ItemResponse] = []
    for position, (difficulty, correct, given) in enumerate(
        zip(difficulties, correct_letters, given_letters, strict=True), start=1
    ):
        given_up = (given or "").upper()
        skipped = given_up in ("", skipped_letter)
        responses.append(
            ItemResponse(
                question_id=position,
                difficulty=float(difficulty),
                is_correct=(not skipped) and given_up == (correct or "").upper(),
                skipped=skipped,
            )
        )
    return responses


def estimate_from_letters(
    difficulties: Sequence[float],
    correct_letters: Sequence[str],
    given_letters: Sequence[str],
    **kwargs: float,
) -> RaschEstimate:
    """Logitlar/kalit/javoblar bo'yicha to'liq Rasch bahosi (θ, SE, 0..100)."""
    return estimate_theta(
        responses_from_letters(difficulties, correct_letters, given_letters), **kwargs
    )


def responses_from_letters_correct_count(
    difficulties: Sequence[float],
    correct_letters: Sequence[str],
    given_letters: Sequence[str],
) -> int:
    """Yordamchi: to'g'ri javoblar sonini (xom ball) hisoblaydi."""
    return sum(
        1
        for response in responses_from_letters(difficulties, correct_letters, given_letters)
        if response.is_correct
    )
