"""Item darajasidagi baholash natijalari (keyingi item-level modelga tayyor qatlam).

Bu modul baholashning **yagona hisoblash nuqtasi**: `services/grading.py` ham,
`services/solutions.py` ham faqat shu yerdan foydalanadi — mantiq ikki joyda
takrorlanmaydi.

Uch daraja
----------
1. `ScoringContext`  — baholash konteksti (imtihon, kalit, `b` lar, rejim);
2. `ItemScoreResult` — **har bir savol uchun** natija: savol raqami, tur,
   belgi (`label`), kalit, o'quvchi javobi, to'g'ri/noto'g'ri, berilgan ball;
3. `ScoringSnapshot` — kelajakdagi `scoring_snapshots` +
   `scoring_snapshot_items` yozuvlarining **tayyor ko'rinishi**.

Muhim: hozir bazaga **hech narsa yozilmaydi** — bu modul faqat obyekt quradi.
Kelajakda yozish uchun tayyor ulanish nuqtasi — `ScoringSnapshotWriter`
interfeysi (hozircha `NullSnapshotWriter`, ya'ni hech narsa qilmaydigan
adapter).

Rejimlar (opt-in)
-----------------
* `ScoringMode.LETTERS`    — eski imtihonlar: faqat A–D harflar
  (xulq **o'zgarmagan**);
* `ScoringMode.ITEM_LEVEL` — MVP formasi: 1–32 → A–D, 33–35 → A–F,
  36–45 → sonli (`NUMERIC_TOLERANCE` bilan); kalitda **qism belgilari** bo'lsa
  (`36a`/`36b`) har bir qism **alohida** savol (Phase 3, Step 3).

Item to'plamini kalitdagi belgilar beradi, shu sababli xom ball ham, Rasch
to'plami ham barqaror (masalan 35 variant + 20 qism = 55 savol).

Rejimni kalitdagi `|` bloki belgilaydi (`form_layout.is_mvp_key`), ya'ni eski
kalitlar hech qachon item-level yo'liga tushmaydi.

Rasch modeli (`services/rasch.py`) **o'zgarmagan** — bu modul faqat unga
tayyor `ItemResponse` ro'yxatini beradi.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final, Mapping, Protocol, Sequence

import config
from database.models import SKIPPED, Exam
from database.repository import Repositories
from services import answer_key, exam_service, form_layout, rasch

logger = logging.getLogger(__name__)

# `scoring_snapshots.engine_version` — hisoblash versiyasi (takrorlanuvchanlik).
SCORING_ENGINE_VERSION: Final[str] = "1.0"

# `scoring_snapshots.model` ustunidagi ruxsat etilgan qiymat.
SCORING_MODEL_RASCH: Final[str] = "rasch_1pl"

# `scoring_snapshot_items.score_status` — hozircha hamma savol avtomatik baholanadi.
SCORE_STATUS_AUTO: Final[str] = "auto_scored"

# `scoring_snapshot_items.b_source` — MVP'da `b` o'qituvchi kiritgan logitlardan
# olinadi (kalibrlash keyingi bosqichda `classical`/`anchor` beradi).
B_SOURCE_DEFAULT: Final[str] = "default"

# `b` o'qituvchining oldindan bahosidan (foiz) hisoblangan bo'lsa shu qiymat
# yoziladi — `item_parameters.source` CHECK lug'ati bilan bir xil
# (`database/migrations/004_scoring.sql`).
B_SOURCE_LEGACY_EXPERT: Final[str] = "legacy_expert"

# `scoring_snapshot_items.key_source` — kalit o'qituvchi tomonidan kiritilgan.
KEY_SOURCE_TEACHER: Final[str] = "teacher"


class ScoringContextError(ValueError):
    """Baholash kontekstidagi `b`/identlik xatosi.

    M1: `b` endi identlik kaliti (`question_key`) bo'yicha saqlanadi; kalit
    topilmasa **jimgina `0.0` qaytarilmaydi** — aniq xato ko'tariladi
    (fail-open taqiqlanadi).
    """


class AnswerType(str, Enum):
    """Savol turi — `item_versions.item_type` lug'ati bilan **bir xil**.

    Shu sababli natija obyektini keyingi bosqichda item-level jadvallarga
    o'zgartirmasdan ko'chirish mumkin.
    """

    MCQ4 = "mcq4"
    MCQ6 = "mcq6"
    NUMERIC = "numeric"
    TEXT = "text"

    @property
    def answer_kind(self) -> str:
        """`responses.answer_kind` / `scoring_snapshot_items.answer_kind` qiymati."""
        return "option" if self in (AnswerType.MCQ4, AnswerType.MCQ6) else self.value

    @property
    def options_count(self) -> int:
        """Variantlar soni (ochiq savolda — 0)."""
        return {"mcq4": 4, "mcq6": 6}.get(self.value, 0)

    @property
    def guessing_c(self) -> float:
        """Tasodifiy to'g'ri javob ehtimoli (1/k; ochiq savolda 0.0)."""
        options = self.options_count
        return (1.0 / options) if options else 0.0


class ScoringMode(str, Enum):
    """Baholash yo'li (opt-in)."""

    LETTERS = "letters"
    ITEM_LEVEL = "item_level"


@dataclass(frozen=True, slots=True)
class ItemScoreResult:
    """Bitta savol bo'yicha baholash natijasi (yagona ko'rinish).

    Maydonlar ikki manbaga tayyor: (a) hisobot/✅-❌ ko'rinishi, (b) kelajakdagi
    `scoring_snapshot_items` satri (`item_version_id`, `item_ref` hozircha
    `None` — item-level ulanish keyingi bosqichda to'ldiriladi).
    """

    question_number: int
    answer_type: AnswerType
    correct_answer: str | None
    given_answer: str | None
    is_correct: bool
    score_awarded: float
    max_score: float = 1.0
    difficulty: float = 0.0
    item_version_id: int | None = None
    item_ref: str | None = None
    # Phase 3 Step 3: savol belgisi (`"36"`, `"36a"`, `"36b"`). `36a` va `36b`
    # bir pozitsiyani (36) bo'lishadi — belgi ularni ajratadi (Step 4: per-part
    # identifikatsiya va qism `b` lari shu maydon ustida quriladi).
    label: str | None = None

    @property
    def question_key(self) -> str:
        """Savol identifikatori: belgi bo'lsa — belgi, aks holda pozitsiya."""
        return self.label or str(self.question_number)

    @property
    def answer_kind(self) -> str:
        """`option` / `numeric` / `text` (turi)."""
        return self.answer_type.answer_kind

    @property
    def is_omitted(self) -> bool:
        """O'quvchi bu savolga javob bermaganmi?"""
        return self.given_answer is None

    @property
    def match_rule(self) -> str:
        """Taqqoslash qoidasi: `exact` (variant) yoki `tolerance` (sonli)."""
        return "tolerance" if self.answer_type is AnswerType.NUMERIC else "exact"

    @property
    def guessing_c(self) -> float:
        """Tasodifiy to'g'ri javob ehtimoli (mcq4: 0.25, mcq6: 0.1667, sonli: 0.0)."""
        return self.answer_type.guessing_c


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Baholash konteksti: **nimani**, **qanday kalit** va **qaysi `b`** bilan baholash.

    `from_exam()` — imtihon yozuvidan kontekst quradi va rejimni kalitdagi `|`
    bloki bo'yicha aniqlaydi (opt-in). Bir kontekst ko'p javob uchun qayta
    ishlatiladi (`grade_exam` shunday qiladi).
    """

    exam_id: int
    total_questions: int
    answer_key: str
    #: M1: `b` **identlik kaliti** (`question_key`) bo'yicha saqlanadi —
    #: `{question_key: b}`. Avvalgi pozitsiyali `tuple[float, ...]` o'rniga.
    b_by_key: Mapping[str, float]
    mode: ScoringMode
    tolerance: float = form_layout.NUMERIC_TOLERANCE
    engine_version: str = SCORING_ENGINE_VERSION
    b_source: str = B_SOURCE_DEFAULT

    @classmethod
    def from_exam(cls, exam: Exam) -> ScoringContext:
        """Imtihon yozuvidan kontekst quradi (xato bermaydi, hamma qiymat bor).

        `b_source` — `b` qayerdan olinganini bildiradi: o'qituvchi foiz
        kiritgan bo'lsa (`b != 0`) `legacy_expert` (muallif bahosi), aks holda
        `default`.
        """
        difficulties = tuple(exam_service.effective_difficulties(exam))
        # M1: pozitsiyali qiymatlarni **identlik kaliti** bo'yicha saqlaymiz.
        # Manba hozircha o'zgarmagan (`exams.difficulty_logits`): bir pozitsiyaga
        # bitta `b`; kalit `str(position)` (`"1".."N"`). Qismlar (`36a`/`36b`)
        # o'z kaliti bilan topilmasa — pozitsiya (`"36"`) zaxirasidan oladi
        # (`difficulty_of()`), ya'ni joriy xulq saqlanadi.
        b_by_key = {
            str(position): float(value)
            for position, value in enumerate(difficulties, start=1)
        }
        return cls(
            exam_id=int(exam.exam_id),
            total_questions=max(int(exam.total_questions or 0), 0),
            answer_key=str(exam.answer_key or ""),
            b_by_key=b_by_key,
            mode=(
                ScoringMode.ITEM_LEVEL
                if form_layout.is_mvp_key(exam.answer_key)
                else ScoringMode.LETTERS
            ),
            b_source=(
                B_SOURCE_LEGACY_EXPERT
                if any(abs(value) > 0.0 for value in b_by_key.values())
                else B_SOURCE_DEFAULT
            ),
        )

    @property
    def is_item_level(self) -> bool:
        """MVP formasi (A–F + sonli) rejimimi?"""
        return self.mode is ScoringMode.ITEM_LEVEL

    @property
    def numeric_positions(self) -> frozenset[int]:
        """Sonli savollar pozitsiyalari (eski rejimda — bo'sh)."""
        if not self.is_item_level:
            return frozenset()
        return frozenset(form_layout.numeric_positions(self.total_questions))

    @property
    def allowed_options(self) -> tuple[str, ...]:
        """Ruxsat etilgan variant harflari (eski rejimda `config.ANSWER_OPTIONS`)."""
        if not self.is_item_level:
            return tuple(config.ANSWER_OPTIONS)
        return form_layout.allowed_options(self.total_questions)

    def difficulty_of(self, question_key: str, position: int | None = None) -> float:
        """Savol identifikatori (`question_key`) bo'yicha `b` (logit).

        M1: `b` endi **identlik kaliti** bo'yicha saqlanadi (`b_by_key`),
        pozitsiya bo'yicha emas. Qidiruv tartibi:

        1. `question_key` (masalan `"1"`, `"36a"`) — asosiy, kalit bo'yicha;
        2. `position` (`str(position)`, masalan `"36"`) — **pozitsiyali manba**
           uchun zaxira (manba `exams.difficulty_logits` bir pozitsiyaga bitta
           qiymat beradi; `36a`/`36b` shu zaxira orqali pozitsiya qiymatini oladi
           — M2 gacha, joriy xulq saqlanadi).

        Jimgina `0.0` **qaytarilmaydi** — topilmasa `ScoringContextError`.

        Raises:
            ScoringContextError: kalit ham, pozitsiya ham topilmasa.
        """
        value = self.b_by_key.get(question_key)
        if value is None and position is not None:
            value = self.b_by_key.get(str(position))
        if value is None:
            raise ScoringContextError(
                f"`b` topilmadi: question_key={question_key!r}, position={position!r}"
            )
        return float(value)

    def with_answer_key(self, answer_key: str) -> ScoringContext:
        """Xuddi shu kontekst, lekin **boshqa kalit** bilan (rejim qayta aniqlanadi).

        Item-level oqimda kalit `form_versions` dan olinadi (legacy
        `exams.answer_key` dan farq qilishi mumkin: MVP kaliti A–F va sonli
        blokni o'z ichiga oladi).
        """
        return replace(
            self,
            answer_key=str(answer_key or ""),
            mode=(
                ScoringMode.ITEM_LEVEL
                if form_layout.is_mvp_key(answer_key)
                else ScoringMode.LETTERS
            ),
        )


def _answer_type(context: ScoringContext, label: int | str) -> AnswerType:
    """Savol belgisi uchun tur: `36`, `36a`, `36b` (Phase 3 Step 3).

    Qism belgisi (`36a`) pozitsiya bo'yicha aniqlanadi (`split_label`) — shu
    sababli `36a`/`36b` ham `numeric` bo'ladi, `1` esa `mcq4`.

    Eski (`LETTERS`) rejimda kalit formati faqat A–D ni biladi, shuning uchun
    hamma savol `mcq4` deb olinadi — bu o'sha rejimda **haqiqatan** qo'llangan
    qoidani aks ettiradi.
    """
    if not context.is_item_level:
        return AnswerType.MCQ4
    position: int = 0
    if isinstance(label, str):
        try:
            position, _part = answer_key.split_label(label)
        except ValueError:
            return AnswerType.TEXT  # noma'lum belgi — baholanmaydigan tur
    else:
        position = int(label)
    options = form_layout.options_of(position)
    if not options:
        return AnswerType.NUMERIC
    return AnswerType.MCQ6 if len(options) > 4 else AnswerType.MCQ4


def build_item_results(
    context: ScoringContext, submitted_answers: str
) -> tuple[ItemScoreResult, ...]:
    """Har bir savol uchun natija obyektlarini quradi (**yagona hisoblash nuqtasi**).

    `grading` (baholash + hisobot) ham, `solutions` (tahlil ✅/❌) ham faqat shu
    funksiyadan foydalanadi.

    Phase 3 Step 3: har bir natija **belgi** bilan qaytadi (`36`, `36a`,
    `36b`) — `36a` va `36b` bir pozitsiyani (36) bo'lishsa ham ajralib turadi
    (`Outcome.label or str(position)`).

    Raises:
        answer_key.AnswerKeyError: kalit yoki javoblar formati buzuq bo'lsa.
    """
    total = context.total_questions
    if total <= 0:
        return ()

    rows: list[tuple[str, int, str | None, str | None, bool]]
    if context.is_item_level:
        rows = [
            (
                outcome.label or str(outcome.position),
                outcome.position,
                outcome.correct_display,
                outcome.given_display,
                outcome.is_correct,
            )
            for outcome in form_layout.score_items(
                context.answer_key, submitted_answers, total
            )
        ]
    else:
        correct_letters = answer_key.parse_answer_key(context.answer_key, total)
        given_letters = answer_key.parse_submitted(submitted_answers, total)
        rows = [
            (
                str(position),
                position,
                correct,
                None if given == SKIPPED else given,
                given != SKIPPED and given == correct,
            )
            for position, (correct, given) in enumerate(
                zip(correct_letters, given_letters, strict=True), start=1
            )
        ]

    return tuple(
        ItemScoreResult(
            question_number=position,
            label=label,
            answer_type=_answer_type(context, label),
            correct_answer=correct,
            given_answer=given,
            is_correct=is_correct,
            score_awarded=1.0 if is_correct else 0.0,
            # M1: `b` **identlik kaliti** bo'yicha olinadi
            # (`question_key = label or str(position)`), pozitsiya bo'yicha emas.
            difficulty=context.difficulty_of(label or str(position), position),
        )
        for label, position, correct, given, is_correct in rows
    )


def correct_count(results: Sequence[ItemScoreResult]) -> int:
    """To'g'ri javoblar soni (`raw_score`)."""
    return sum(1 for result in results if result.is_correct)


def total_score(results: Sequence[ItemScoreResult]) -> float:
    """Berilgan ballar yig'indisi (keyinchalik qismiy ball uchun tayyor)."""
    return sum(result.score_awarded for result in results)


def omitted_count(results: Sequence[ItemScoreResult]) -> int:
    """Javob berilmagan savollar soni."""
    return sum(1 for result in results if result.is_omitted)


def item_responses(
    results: Sequence[ItemScoreResult], context: ScoringContext
) -> list[rasch.ItemResponse]:
    """Natijalarni Rasch uchun `ItemResponse` ro'yxatiga aylantiradi.

    `rasch.py` **o'zgarmagan** — u faqat `is_correct`/`difficulty` ni o'qiydi
    (`skipped` esa ma'lumot uchun beriladi).
    """
    return [
        rasch.ItemResponse(
            question_id=result.question_number,
            difficulty=result.difficulty,
            is_correct=result.is_correct,
            skipped=result.is_omitted,
        )
        for result in results
    ]


def estimate_theta(
    results: Sequence[ItemScoreResult], context: ScoringContext, **kwargs: float
) -> rasch.RaschEstimate:
    """θ ni MLE (Newton-Raphson) usulida baholaydi — `rasch.estimate_theta` orqali."""
    return rasch.estimate_theta(item_responses(results, context), **kwargs)


def _b_checksum(context: ScoringContext) -> str:
    """Ishlatilgan `b` to'plamining hashi (takrorlanuvchanlik uchun).

    M1: `b` endi identlik kalitli xarita (`b_by_key`). Hash **deterministik**:
    kalitlar bo'yicha **saralangan** tartibda olinadi — `dict` iteratsiya
    tartibiga **bog'liq emas**. Bir xil `(kalit, qiymat)` to'plami har doim
    bir xil checksum beradi.
    """
    payload = json.dumps(
        [
            [key, round(float(context.b_by_key[key]), 4)]
            for key in sorted(context.b_by_key)
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotItem:
    """`scoring_snapshot_items` satrining **tayyor** ko'rinishi (hozir yozilmaydi).

    Maydon nomlari migratsiyadagi ustun nomlari bilan bir xil — keyingi
    bosqichda INSERT shunchaki shu qiymatlarni bog'laydi.
    """

    position: int
    display_label: str
    answer_kind: str
    key_used: str | None
    raw_answer: str | None
    normalized_answer: str | None
    score_awarded: float
    max_score: float
    score_status: str
    match_rule: str
    b_used: float
    theta_used: float | None
    guessing_c: float
    capture_status: str
    engine_version: str
    item_version_id: int | None = None
    item_ref: str | None = None
    b_source: str = B_SOURCE_DEFAULT


@dataclass(frozen=True, slots=True)
class ScoringSnapshot:
    """`scoring_snapshots` + `scoring_snapshot_items` uchun tayyor to'plam.

    Diqqat: hozir bu obyekt **faqat quriladi**, bazaga yozilmaydi
    (`attempt_id`/`form_version_id` ham `None` — item-level model hali
    ishlatilmaydi).
    """

    mode: ScoringMode
    exam_id: int
    model: str
    theta: float
    theta_se: float | None
    log_likelihood: float
    raw_score: int
    total_items: int
    omitted_count: int
    not_reached_count: int
    scaled_score: float
    scaled_min: float
    scaled_max: float
    theta_bound: float
    engine_version: str
    b_checksum: str
    items: tuple[SnapshotItem, ...]
    is_extreme_low: bool = False
    is_extreme_high: bool = False
    attempt_id: int | None = None
    form_version_id: int | None = None


def build_scoring_snapshot(
    context: ScoringContext,
    results: Sequence[ItemScoreResult],
    estimate: rasch.RaschEstimate,
    *,
    attempt_id: int | None = None,
    form_version_id: int | None = None,
) -> ScoringSnapshot:
    """Baholash natijasidan kelajakdagi snapshot to'plamini quradi.

    Hech qanday I/O yo'q — sof ma'lumot. `scoring_snapshot_items.raw_answer`
    ataylab `None`: Web App xom matnni (masalan `12,5`) saqlamaydi, kiritish
    darhol normallashtiriladi (bu ma'lumot keyingi bosqichda yig'iladi).

    `display_label` — savol **belgisi** (`36`, `36a`, `36b`): `36a` va `36b`
    bir pozitsiyani (36) bo'lishadi, shu sababli belgi snapshotda saqlanadi
    (`position` esa o'zgarmaydi).
    """
    items = tuple(
        SnapshotItem(
            position=result.question_number,
            display_label=result.question_key,
            answer_kind=result.answer_kind,
            key_used=result.correct_answer,
            raw_answer=None,
            normalized_answer=result.given_answer,
            score_awarded=result.score_awarded,
            max_score=result.max_score,
            score_status=SCORE_STATUS_AUTO,
            match_rule=result.match_rule,
            b_used=result.difficulty,
            theta_used=estimate.theta,
            guessing_c=result.guessing_c,
            capture_status="blank" if result.is_omitted else "answered",
            engine_version=context.engine_version,
            b_source=context.b_source,
            item_version_id=result.item_version_id,
            item_ref=result.item_ref,
        )
        for result in results
    )

    return ScoringSnapshot(
        mode=context.mode,
        exam_id=context.exam_id,
        model=SCORING_MODEL_RASCH,
        theta=estimate.theta,
        theta_se=estimate.standard_error,
        log_likelihood=estimate.log_likelihood,
        raw_score=correct_count(results),
        total_items=len(results),
        omitted_count=omitted_count(results),
        not_reached_count=0,  # taqdimot telemetriyasi hali yo'q (docs/09 §1 A)
        scaled_score=estimate.scaled_score,
        scaled_min=float(config.SCALED_CAP_MIN),
        scaled_max=float(config.SCALED_CAP_MAX),
        theta_bound=float(config.THETA_BOUND),
        engine_version=context.engine_version,
        b_checksum=_b_checksum(context),
        items=items,
        is_extreme_low=estimate.is_extreme and estimate.theta <= 0,
        is_extreme_high=estimate.is_extreme and estimate.theta >= 0,
        attempt_id=attempt_id,
        form_version_id=form_version_id,
    )


def validate_context(context: ScoringContext) -> None:
    """Kalitni baholashdan oldin bir marta tekshiradi.

    Tekshiruv **baholashning o'zi** orqali boradi (bo'sh javob bilan), shuning
    uchun alohida validatsiya qoidasi yo'q — kalit formati baholash bilan doim
    bir xil talqin qilinadi.

    Raises:
        answer_key.AnswerKeyError: kalit formati buzuq bo'lsa.
    """
    build_item_results(context, "")


class ScoringSnapshotWriter(Protocol):
    """Snapshot'ni saqlash interfeysi (keyingi bosqich: `scoring_snapshots`).

    Hozirgi standart — `NullSnapshotWriter`: snapshot quriladi, lekin bazaga
    yozilmaydi. Item-level model ulanganda faqat shu interfeysni amalga
    oshiruvchi sinf qo'shiladi — `grading.grade_exam` shu nuqtada chaqiradi.
    """

    async def write(self, snapshot: ScoringSnapshot) -> None:
        """Snapshot'ni saqlaydi (implementatsiya tomonidan)."""
        ...


class NullSnapshotWriter:
    """Hech narsa saqlamaydigan adapter (hozirgi standart xulq)."""

    async def write(self, snapshot: ScoringSnapshot) -> None:
        """Snapshot qabul qilinadi va tashlab yuboriladi (DB yozuvi yo'q)."""
        return None


#: Joriy yozuvchi. Item-level model ulanganda shu nuqtada almashtiriladi.
SNAPSHOT_WRITER: ScoringSnapshotWriter = NullSnapshotWriter()


class DbSnapshotWriter:
    """`ScoringSnapshotWriter` ning **haqiqiy (DB)** implementatsiyasi.

    Yozadi:
      * `scoring_snapshots` — baholash snapshot'i (θ, SE, raw/scaled, `b` hashi);
      * `scoring_snapshot_items` — har bir savol natijasi (kalit, `b`, ball, holat);
      * `attempts` — urinish natijasi (`save_result`: θ, SE, ball, hisoblagichlar).

    Item-level identifikatorlar (`form_item_id`, `item_id`, `item_version_id`)
    forma versiyasidan olinadi (`form_items` + `item_versions`), chunki
    `scoring_snapshot_items` da ular majburiy (FK). Ular topilmasa — xatolik
    ko'tariladi (chaqiruvchi uni ushlab, gradingni davom ettiradi).
    """

    def __init__(
        self,
        repos: Repositories,
        *,
        attempt_id: int,
        form_version_id: int,
        session_id: int | None = None,
        computed_by: str = "system",
    ) -> None:
        """Yozuvchini tayyorlaydi (urinish allaqachon mavjud bo'lishi kerak).

        Args:
            repos: repository konteyneri (`snapshots`, `attempts`, `forms`).
            attempt_id: `attempts.attempt_id` (FK).
            form_version_id: `form_versions.form_version_id` (FK).
            session_id: `exam_sessions.session_id` (ixtiyoriy, snapshot satriga yoziladi).
            computed_by: `scoring_snapshots.computed_by` (`system`/`admin`/`regrade`).
        """
        self._repos = repos
        self._attempt_id = int(attempt_id)
        self._form_version_id = int(form_version_id)
        self._session_id = None if session_id is None else int(session_id)
        self._computed_by = computed_by
        self._items: (
            tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]] | None
        ) = None

    async def _form_items(
        self,
    ) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
        """`(label → satr, position → satr)` xaritalari (birinchi chaqiruvda o'qiladi).

        Label xaritasi qismli savollarni (`36a`, `36b`) ajratadi — bir pozitsiyada
        ikki satr bo'lganda har biriga **o'z** `form_item_id` tanlanadi. Pozitsiya
        xaritasi esa legacy (qismsiz) yozuvlar uchun avvalgi xulqni saqlaydi.
        """
        if self._items is None:
            self._items = (
                await self._repos.forms.items_by_label(self._form_version_id),
                await self._repos.forms.items_by_position(self._form_version_id),
            )
        return self._items

    @staticmethod
    def _resolve(
        item: SnapshotItem,
        by_label: Mapping[str, dict[str, Any]],
        by_position: Mapping[int, dict[str, Any]],
    ) -> tuple[Mapping[str, Any] | None, SnapshotItem, str | None]:
        """Snapshot elementi uchun `form_items` satrini tanlaydi.

        Qaytaradi: ``(form_item, item, row_label)`` — `_item_row` kutgan tartibda.

        * qismli belgi (`36a`, `36b`) → **label** xaritasidan (`row_label` = belgi):
          har bir qism o'z `form_item_id` sini oladi;
        * qismsiz belgi (`36`) → avvalgidek **pozitsiya** xaritasidan (legacy xulq).
        """
        label = item.display_label or str(item.position)
        if label == str(item.position):
            return by_position.get(item.position), item, None
        return by_label.get(label), item, label

    @staticmethod
    def _item_row(
        form_item: Mapping[str, Any] | None,
        item: SnapshotItem,
        row_label: str | None = None,
    ) -> tuple[Any, ...]:
        """`scoring_snapshot_items` uchun 22 ustunli satr (repository kutgan tartib).

        `row_label` — qismli (`36a`) savol belgisi: berilganda `display_label`
        ustuni **aynan shu belgi** bo'ladi (formada qanday yozilganidan qat'i
        nazar). Legacy (qismsiz) holatda `None` — `display_label` avvalgidek
        `form_items` satridan olinadi.

        Raises:
            ValueError: savol formada yo'q yoki item-level bog'lanishi bo'sh bo'lsa.
        """
        shown = str(item.position) if row_label is None else row_label
        if form_item is None:
            raise ValueError(
                f"{shown}-savol forma versiyasida topilmadi — snapshot yozilmadi."
            )
        item_id = form_item.get("item_id")
        item_version_id = form_item.get("item_version_id")
        if item_id is None or item_version_id is None:
            raise ValueError(
                f"{shown}-savolda item-level bog'lanish yo'q "
                "(`form_items.item_version_id` bo'sh) — snapshot yozilmadi."
            )
        return (
            int(form_item["form_item_id"]),
            int(item_id),
            int(item_version_id),
            str(row_label or form_item.get("display_label") or item.display_label),
            int(item.position),
            None,  # testlet_ref
            float(item.b_used),
            item.b_source,
            item.theta_used,
            float(item.guessing_c),
            item.key_used,
            None,  # key_version_no
            KEY_SOURCE_TEACHER,
            item.answer_kind,
            item.raw_answer,
            item.normalized_answer,
            float(item.score_awarded),
            float(item.max_score),
            item.score_status,
            item.match_rule,
            item.capture_status,
            item.engine_version,
        )

    async def write(self, snapshot: ScoringSnapshot) -> None:
        """Snapshot + savol natijalarini yozadi va urinish natijasini yangilaydi.

        Savol → `form_items` satri **belgi** bo'yicha topiladi (`36a`, `36b`) —
        bir pozitsiyadagi qismlar har xil `form_item_id` oladi. Legacy (qismsiz)
        belgilar avvalgidek pozitsiya bo'yicha topiladi.

        Snapshot yozilmasa (forma bog'lanishi yo'q, cheklov buzilsa va h.k.)
        xato **log qilinadi** va ochiq tranzaksiya qaytariladi — urinish
        natijasi (`attempts`) baribir saqlanadi.
        """
        try:
            by_label, by_position = await self._form_items()
            rows = [
                self._item_row(*self._resolve(item, by_label, by_position))
                for item in snapshot.items
            ]
            await self._repos.snapshots.save(
                attempt_id=self._attempt_id,
                form_version_id=self._form_version_id,
                session_id=self._session_id,
                theta=snapshot.theta,
                theta_se=snapshot.theta_se,
                log_likelihood=snapshot.log_likelihood,
                raw_score=snapshot.raw_score,
                total_items=snapshot.total_items,
                omitted_count=snapshot.omitted_count,
                not_reached_count=snapshot.not_reached_count,
                scaled_score=snapshot.scaled_score,
                scaled_min=snapshot.scaled_min,
                scaled_max=snapshot.scaled_max,
                theta_bound=snapshot.theta_bound,
                engine_version=snapshot.engine_version,
                b_checksum=snapshot.b_checksum,
                model=snapshot.model,
                is_final=True,  # regrade'da avvalgi yakuniy snapshot `is_final = 0` bo'ladi
                computed_by=self._computed_by,
                items=rows,
            )
        except Exception:
            # `snapshots.save()` tranzaksiyani qaytarmaydi (repository'da rollback
            # yo'q), `Database.execute*` esa commit qiladi — shu sababli ochiq
            # tranzaksiyani yopmasak, keyingi commit **qisman** snapshotni
            # yozib yuborardi. Xato yutiladi: urinish natijasi saqlanishi kerak.
            await self._repos.db.connection.rollback()
            logger.exception(
                "Snapshot yozilmadi (attempt_id=%s) — urinish natijasi baribir saqlanadi",
                self._attempt_id,
            )

        answered = max(
            snapshot.total_items - snapshot.omitted_count - snapshot.not_reached_count, 0
        )
        await self._repos.attempts.save_result(
            self._attempt_id,
            theta=snapshot.theta,
            theta_se=snapshot.theta_se,
            scaled_score=snapshot.scaled_score,
            raw_score=snapshot.raw_score,
            n_answered=answered,
            n_omitted=snapshot.omitted_count,
            n_not_reached=snapshot.not_reached_count,
            engine_version=snapshot.engine_version,
            is_extreme_low=snapshot.is_extreme_low,
            is_extreme_high=snapshot.is_extreme_high,
        )