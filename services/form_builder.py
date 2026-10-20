"""O'qituvchi uchun item-level **Form Builder** (forma + kalit + savollar).

Bitta chaqiruvda quyidagilar yaratiladi:

    forms → form_versions → form_items
                            └─ har bir savol uchun: items + item_versions
                               (`item_type`, `correct_option`, `answer_spec`)

MVP formasi qoidalari **yagona manbadan** olinadi (`services/form_layout.py`):

    1–32   → A–D    → `mcq4`
    33–35  → A–F    → `mcq6`
    36–45  → sonli  → `numeric` (javob `answer_spec` da: `accepted`, `tolerance`)

Har bir savol uchun saqlanadi:

    form_items     : position, display_label, part, section_no, correct_option,
                     options_count, item_version_id, points
    item_versions  : item_type (answer_kind), correct_option, answer_spec (JSON),
                     max_score, key_source='teacher'

Muhim cheklov (sxema muzlatilgan — DDL yozilmaydi): `form_items` jadvalida
`answer_kind`/`answer_spec` ustunlari yo'q, ular `item_versions` da turadi.
Shuning uchun builder har bir savol uchun item versiyasini ham yaratadi.

`b` (logit) hozircha faqat tekshiriladi va natijada qaytariladi: u
`item_parameters` jadvaliga kalibrlash bosqichida yoziladi (o'sha modul
qo'shilmaguncha saqlanmaydi).

Legacy (A–D) va MVP (`|` blokli) kalitlar **bir xil** oqimdan o'tadi: ikkalasi
uchun ham forma yaratiladi.

**Qism kafolati (`36–45`):** har bir ochiq savol **doim** `a` va `b` qismlariga
bo'linadi (`form_layout.parts_of` — yagona manba), chunki test qog'ozida ham
`a)` va `b)` bor. Kalitda qiymat bo'lmasa ham savol yaratiladi — u
`answer_spec.accepted = []` bilan saqlanadi va baholashda doim "noto'g'ri"
hisoblanadi (talab: qiymatsiz qism noto'g'ri). Belgilanmagan (legacy) kalitdagi
`36:12.5` qiymati `36a` qismiga tushadi.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from database.repository import Repositories
from services import answer_key, exam_service, form_layout, scoring

logger = logging.getLogger(__name__)

#: MVP savolining standart balli (`form_items.points`, `item_versions.max_score`).
DEFAULT_POINTS: Final[float] = 1.0

#: `answer_spec` JSON turi — baholash qoidasi (docs/01 §`item_versions`).
SPEC_KIND_OPTION: Final[str] = "option"
SPEC_KIND_NUMERIC: Final[str] = "numeric"


class FormBuildError(ValueError):
    """Forma yaratishdagi kiritish xatosi (foydalanuvchiga ko'rsatiladigan izoh)."""


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    """Bitta savolning item-level spetsifikatsiyasi (hali yozilmagan ko'rinish)."""

    position: int
    display_label: str
    part: str
    section_no: int | None
    answer_type: scoring.AnswerType
    options_count: int
    correct_option: str | None
    correct_numeric: float | None
    answer_spec: str
    points: float
    difficulty: float

    @property
    def answer_kind(self) -> str:
        """`option` / `numeric` (`responses.answer_kind` lug'ati)."""
        return self.answer_type.answer_kind

    @property
    def item_type(self) -> str:
        """`item_versions.item_type` qiymati (`mcq4`/`mcq6`/`numeric`)."""
        return self.answer_type.value

    def as_item_row(self) -> dict[str, Any]:
        """`repos.forms.create_full_form()` kutgan lug'at ko'rinishi."""
        return {
            "position": self.position,
            "display_label": self.display_label,
            "part": self.part,
            "section_no": self.section_no,
            "item_type": self.item_type,
            "correct_option": self.correct_option,
            "options_count": self.options_count,
            "answer_spec": self.answer_spec,
            "points": self.points,
            "difficulty": float(self.difficulty),
        }


@dataclass(frozen=True, slots=True)
class FormBuildResult:
    """`FormBuilder.create_form()` natijasi (admin ustasi uchun tayyor API)."""

    form_id: int
    form_version_id: int
    title: str
    test_code: str
    total_questions: int
    answer_key: str
    difficulty_logits: tuple[float, ...]
    questions: tuple[QuestionSpec, ...]

    @property
    def layout(self) -> tuple[dict[str, Any], ...]:
        """Savollar bo'limlari (`/api/v2/verify-code` qaytaradigan ko'rinish)."""
        return tuple(form_layout.layout_ranges(self.total_questions))

    @property
    def kinds(self) -> dict[str, int]:
        """Savol turlari bo'yicha soni, masalan `{"mcq4": 32, "mcq6": 3, "numeric": 10}`."""
        counts: dict[str, int] = {}
        for question in self.questions:
            counts[question.item_type] = counts.get(question.item_type, 0) + 1
        return counts

    @property
    def has_item_versions(self) -> bool:
        """Har bir savol item versiyasiga bog'langanmi (answer_spec saqlangan)."""
        return all(
            question.answer_spec and question.answer_type is not None
            for question in self.questions
        )


def _build_answer_spec(
    answer_type: scoring.AnswerType,
    correct_option: str | None,
    correct_numeric: float | None,
) -> str:
    """Baholash qoidasini JSON sifatida quradi (docs/01 `item_versions`).

    * variant savol → ``{"kind": "option", "correct": "A", "options_count": 4,
      "guessing_c": 0.25}``
    * sonli savol → ``{"kind": "numeric", "accepted": [12.5],
      "tolerance": 1e-06}``
    """
    if answer_type is scoring.AnswerType.NUMERIC:
        spec: dict[str, Any] = {
            "kind": SPEC_KIND_NUMERIC,
            "accepted": [] if correct_numeric is None else [float(correct_numeric)],
            "tolerance": float(form_layout.NUMERIC_TOLERANCE),
        }
    else:
        spec = {
            "kind": SPEC_KIND_OPTION,
            "correct": correct_option,
            "options_count": answer_type.options_count,
            "guessing_c": answer_type.guessing_c,
        }
    return json.dumps(spec, ensure_ascii=False, sort_keys=True)


class FormBuilder:
    """Forma + kalit + savollarni **item-level** ko'rinishda yaratadi.

    Yozuv `repos.forms.create_full_form()` orqali, **bitta tranzaksiyada**
    bajariladi: biror qadam yiqilsa hech narsa saqlanmaydi.
    """

    def __init__(self, repos: Repositories) -> None:
        self._repos = repos

    async def create_form(
        self,
        *,
        title: str,
        test_code: str,
        total_questions: int,
        answer_key: str,
        difficulty_logits: Sequence[float] | str | None = None,
        subject_code: str | None = None,
        parts: Sequence[str] = (),
        status: str = "published",
        created_by: int | None = None,
        item_ref_prefix: str | None = None,
        points: float = DEFAULT_POINTS,
    ) -> FormBuildResult:
        """Item-level formani yaratadi (`forms` + `form_versions` + `form_items`).

        Args:
            title: imtihon nomi (3–120 belgi).
            test_code: o'quvchi kiritadigan kod (kamida 4 belgi, harf/raqam).
            total_questions: savollar soni (MVP joylashuvi 45 tagacha qoplaydi).
            answer_key: kanonik kalit — `1A2B…35F|36:12.5,37:3` (33–35 → A–F,
                36–45 → sonli qiymat). 35 tagacha savolda oddiy harfli kalit ham
                qabul qilinadi.
            difficulty_logits: `b` (logit) — matn (`"0.5, -1.2"`), sonlar ro'yxati
                yoki bitta son (hammaga qo'llanadi); bo'sh bo'lsa — 0.0.
            subject_code: fan kodi (ixtiyoriy, `items.subject_code` ga yoziladi).
            parts: qismli savol belgilari (`["36a", "36b"]`).
            status: `form_versions.status` (`draft`/`published`/`retired`).
            created_by: o'qituvchi (Telegram ID).
            item_ref_prefix: `items.item_ref` prefiksi (berilmasa — test kodi).
            points: har bir savolning balli (`form_items.points`).

        Qaytaradi:
            `FormBuildResult` — `form_id`, `form_version_id`, savollar, kalit.

        Raises:
            FormBuildError: kiritish noto'g'ri, kalit to'liq emas yoki test kodi
                band bo'lsa (bunda hech narsa saqlanmaydi).
        """
        clean_title = self._clean_title(title)
        clean_code = self._clean_code(test_code)
        total = self._clean_total(total_questions)
        letters, numeric = self._split_key(answer_key, total)
        logits = self._normalize_logits(difficulty_logits, total)
        questions = self._build_questions(letters, numeric, logits, total, points)
        canonical_key = form_layout.build_canonical(letters, numeric)
        # `forms.parts_json` — qismli savollar belgilari (`["36a","36b"]`). Kalitdan
        # yoki tayyor ro'yxatdan olinadi; qism bo'lmasa — bo'sh (legacy xulq).
        part_labels = tuple(parts) or tuple(
            f"{question.position}{question.part}"
            for question in questions
            if question.part
        )

        try:
            form_id, form_version_id = await self._repos.forms.create_full_form(
                title=clean_title,
                test_code=clean_code,
                total_questions=total,
                answer_key=canonical_key,
                questions=[question.as_item_row() for question in questions],
                subject_code=subject_code,
                item_ref_prefix=item_ref_prefix,
                parts=part_labels,
                status=status,
                created_by=created_by,
            )
        except sqlite3.IntegrityError as exc:
            logger.warning("Forma yozilmadi (integrity): %s — %s", clean_code, exc)
            raise FormBuildError(
                "Formani saqlab bo'lmadi — test kodi band yoki ma'lumotlar "
                "cheklovi buzilgan bo'lishi mumkin. Kodni o'zgartirib qayta "
                "urinib ko'ring."
            ) from exc
        except FormBuildError:
            raise
        except Exception as exc:  # baza xatosi — o'zbekcha izoh bilan
            raise FormBuildError(f"Formani saqlashda xatolik: {exc}") from exc

        logger.info(
            "Item-level forma yaratildi: form_id=%s, versiya=%s, kod=%s, savollar=%d",
            form_id,
            form_version_id,
            clean_code,
            len(questions),
        )
        return FormBuildResult(
            form_id=form_id,
            form_version_id=form_version_id,
            title=clean_title,
            test_code=clean_code,
            total_questions=total,
            answer_key=canonical_key,
            difficulty_logits=tuple(logits),
            questions=questions,
        )

    # -- kiritishni tekshirish -------------------------------------------------
    @staticmethod
    def _clean_title(title: str) -> str:
        """Nomni tekshiradi.

        Raises:
            FormBuildError: nom juda qisqa/uzun bo'lsa.
        """
        try:
            return exam_service.validate_title(title)
        except ValueError as exc:
            raise FormBuildError(str(exc)) from exc

    @staticmethod
    def _clean_code(test_code: str) -> str:
        """Test kodini tekshiradi.

        Raises:
            FormBuildError: kod qisqa yoki noto'g'ri belgilarda bo'lsa.
        """
        try:
            return exam_service.validate_test_code(test_code)
        except ValueError as exc:
            raise FormBuildError(str(exc)) from exc

    @staticmethod
    def _clean_total(total_questions: int) -> int:
        """Savollar sonini tekshiradi (MVP joylashuvi 45 tagacha).

        Raises:
            FormBuildError: son noto'g'ri yoki joylashuv qoplamasa.
        """
        try:
            total = int(total_questions)
        except (TypeError, ValueError) as exc:
            raise FormBuildError("Savollar soni butun son bo'lishi kerak.") from exc
        if total <= 0:
            raise FormBuildError("Savollar soni noldan katta bo'lishi kerak.")

        covered = max(int(section["to"]) for section in form_layout.layout_ranges(total))
        if covered < total:
            raise FormBuildError(
                f"Bu MVP joylashuvi {covered} savolgacha qo'llab-quvvatlaydi "
                f"(so'ralgan: {total})."
            )
        return total

    # -- kalit va logitlar -----------------------------------------------------
    @staticmethod
    def _normalize_logits(
        difficulty_logits: Sequence[float] | str | None, total: int
    ) -> list[float]:
        """`b` (logit) qiymatlarini ro'yxatga aylantiradi (bo'sh bo'lsa — 0.0).

        Raises:
            FormBuildError: qiymatlar soni savollar soniga mos kelmasa.
        """
        if difficulty_logits is None or (
            isinstance(difficulty_logits, str) and not difficulty_logits.strip()
        ):
            return [0.0] * total

        if isinstance(difficulty_logits, str):
            try:
                return exam_service.parse_difficulties_input(difficulty_logits, total)
            except ValueError as exc:
                raise FormBuildError(str(exc)) from exc

        if isinstance(difficulty_logits, (int, float)):
            values = [float(difficulty_logits)]
        else:
            try:
                values = [float(value) for value in difficulty_logits]
            except (TypeError, ValueError) as exc:
                raise FormBuildError(
                    "Qiyinchilik qiymatlari son, sonlar ro'yxati yoki matn bo'lishi kerak."
                ) from exc

        if any(not math.isfinite(value) for value in values):
            raise FormBuildError("Qiyinchilik qiymatlari chekli sonlar bo'lishi kerak.")

        # Foiz ham, logit ham qabul qilinadi — `exam_service` bilan bir xil qoida.
        # (Matn yo'li ham o'sha rejim aniqlashga tayanadi.)
        try:
            mode = exam_service.detect_difficulty_mode(values)
        except ValueError as exc:
            raise FormBuildError(str(exc)) from exc

        if len(values) == 1 and total > 1:
            values *= total
        if len(values) != total:
            raise FormBuildError(
                f"Logitlar soni ({len(values)}) savollar soniga ({total}) teng emas. "
                "Bitta qiymat kiritsangiz — u hamma savolga qo'llanadi."
            )
        if mode == exam_service.MODE_PERCENT:
            return [exam_service.percent_to_logit(value) for value in values]
        return values

    @staticmethod
    def _split_key(
        key_text: str, total: int
    ) -> tuple[list[str], dict[int | str, float]]:
        """Kalitni `(harflar, sonli javoblar)` ko'rinishiga ajratadi.

        Sonli qism kalitlari **qismli** (`"36a"`) yoki **qismsiz** (`36`) bo'lishi
        mumkin: qismli kalitda (`|36a:√5,36b:3/7`) kalitlar belgi ko'rinishida
        qaytadi — shu sababli bir pozitsiyaning ikki qismi ajralib turadi.

        Raises:
            FormBuildError: kalit formati buzuq yoki sonli savollar uchun qiymat
                ko'rsatilmagan bo'lsa.
        """
        if form_layout.is_labeled_key(key_text):
            try:
                return form_layout.parse_labeled_key(key_text, total)
            except answer_key.AnswerKeyError as exc:
                raise FormBuildError(str(exc)) from exc

        if form_layout.is_mvp_key(key_text):
            try:
                return form_layout.parse_key(key_text, total)
            except answer_key.AnswerKeyError as exc:
                raise FormBuildError(str(exc)) from exc

        # Legacy kalitda (`|` bloki yo'q) sonli savollar (36–45) uchun qiymat
        # bo'lmaydi: ular `answer_spec.accepted = []` bilan yaratiladi va
        # baholashda doim "noto'g'ri" hisoblanadi (talab: 36–45 ixtiyoriy).
        # Shu sababli bu yerda xato ko'tarilmaydi.
        try:
            letters = answer_key.parse_answer_key(
                key_text, total, allowed_options=form_layout.allowed_options(total)
            )
        except answer_key.AnswerKeyError as exc:
            raise FormBuildError(str(exc)) from exc
        return letters, {}

    @staticmethod
    def _numeric_maps(
        numeric: Mapping[int | str, float],
    ) -> tuple[dict[int, float], dict[int, dict[str, float]]]:
        """Sonli javoblarni `(qismsiz, {position: {part: qiymat}})` ga ajratadi.

        Kalit `int` (qismsiz: `36`) yoki `str` (`"36"`, `"36a"`) bo'lishi mumkin —
        qismli belgilar alohida guruhga tushadi.
        """
        plain: dict[int, float] = {}
        parts: dict[int, dict[str, float]] = {}
        for key, value in numeric.items():
            if isinstance(key, str):
                number, part = answer_key.split_label(key)
                if part:
                    parts.setdefault(number, {})[part] = float(value)
                    continue
                plain[number] = float(value)
                continue
            plain[int(key)] = float(value)
        return plain, parts

    @staticmethod
    def _build_questions(
        letters: Sequence[str],
        numeric: Mapping[int | str, float],
        logits: Sequence[float],
        total: int,
        points: float,
    ) -> tuple[QuestionSpec, ...]:
        """Har bir savol — qismli bo'lsa har bir **qism** uchun spetsifikatsiya.

        Qismli kalitda (`|36a:√5,36b:3/7`) bir pozitsiya uchun **ikki** satr
        yaratiladi: `display_label="36a"`, `part="a"` va `"36b"`, `"b"`.
        Qismlar uchun `b` authoring qilinmaydi — `difficulty=0.0`
        (`item_parameters`: `b_value=0.0`, `source='default'`, `status='provisional'`).

        Raises:
            FormBuildError: sonli savol uchun kalitda qiymat topilmasa.
        """
        plain, parts = FormBuilder._numeric_maps(numeric)
        specs: list[QuestionSpec] = []
        for section_no, section in enumerate(form_layout.layout_ranges(total), start=1):
            for position in range(int(section["from"]), int(section["to"]) + 1):
                options = tuple(section["options"])
                correct_numeric: float | None = None
                if options:
                    answer_type = (
                        scoring.AnswerType.MCQ6
                        if len(options) > 4
                        else scoring.AnswerType.MCQ4
                    )
                    correct_option: str | None = str(letters[position - 1]).upper()
                else:
                    answer_type = scoring.AnswerType.NUMERIC
                    correct_option = None
                    # QISM KAFOLATI (`form_layout.parts_of` — yagona manba):
                    # 36–45 har doim `a` va `b` ga bo'linadi. Kalitda qiymat
                    # bo'lmasa ham savol YARATILADI — javobsiz (`accepted = []`)
                    # bo'lib, baholashda doim "noto'g'ri" hisoblanadi.
                    question_parts = form_layout.parts_of(position)
                    if question_parts != ("",):
                        keyed: Mapping[str, Any] = parts.get(position) or {}
                        if not keyed:
                            # Legacy (belgilanmagan) kalit: `36:12.5` → `a` qismiga.
                            legacy_value = plain.get(position)
                            if legacy_value is not None:
                                keyed = {"a": legacy_value}
                        for part in question_parts:
                            value = keyed.get(part)
                            specs.append(
                                QuestionSpec(
                                    position=position,
                                    display_label=f"{position}{part}",
                                    part=part,
                                    section_no=section_no,
                                    answer_type=answer_type,
                                    options_count=answer_type.options_count,
                                    correct_option=None,
                                    correct_numeric=value,
                                    answer_spec=_build_answer_spec(
                                        answer_type, None, value
                                    ),
                                    points=float(points),
                                    # Ikkala qism ham pozitsiya logitini oladi
                                    # (bitta matn → o'xshash qiyinchilik;
                                    # kalibrlash keyin aniqlashtiradi).
                                    difficulty=float(logits[position - 1]),
                                )
                            )
                        continue
                    correct_numeric = plain.get(position)

                specs.append(
                    QuestionSpec(
                        position=position,
                        display_label=str(position),
                        part="",
                        section_no=section_no,
                        answer_type=answer_type,
                        options_count=answer_type.options_count,
                        correct_option=correct_option,
                        correct_numeric=(
                            None if correct_numeric is None else float(correct_numeric)
                        ),
                        answer_spec=_build_answer_spec(
                            answer_type, correct_option, correct_numeric
                        ),
                        points=float(points),
                        difficulty=float(logits[position - 1]),
                    )
                )
        return tuple(specs)


async def create_form(repos: Repositories, **kwargs: Any) -> FormBuildResult:
    """Admin handler uchun qulaylik: ``FormBuilder(repos).create_form(**kwargs)``.

    Misol::

        result = await create_form(
            repos,
            title="Matematika — 1-variant",
            test_code="MATH2026",
            total_questions=45,
            answer_key="1A2B…35F|36:12.5,37:3",
            difficulty_logits="-0.5, 0.2, 1.1",
            created_by=message.from_user.id,
        )
        # result.form_id, result.form_version_id, result.kinds, result.layout
    """
    return await FormBuilder(repos).create_form(**kwargs)