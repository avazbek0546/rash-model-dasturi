"""Imtihon javoblarini Rasch modeli bo'yicha baholash.

Oqim
----
1. O'quvchi Web App orqali javob yuboradi (`user_answers.submitted_answers`),
   θ hali hisoblanmaydi (`theta = NULL`) — muddatdan oldin natija oshkor
   bo'lmasligi uchun.
2. `end_time` kelgach javob qabul qilish to'xtaydi va fon vazifasi
   (`grading_loop`) imtihonni baholaydi: har bir javob uchun θ (MLE),
   standart xato va 0–100 shkala hisoblanib bazaga yoziladi.
3. Natijalar faqat `result_time` kelgach ko'rsatiladi (`exam_service`).

Fon vazifasidan tashqari "lazy" zaxira ham bor: natija so'ralganda imtihon
hali baholanmagan bo'lsa, o'sha zahoti baholanadi (`ensure_graded`).
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from typing import Any, Sequence

import config
from database.models import SKIPPED, Exam, ExamSubmission
from database.repository import Repositories
from services import answer_key, exam_service, form_layout, item_statistics, rasch, scoring, subjects

logger = logging.getLogger(__name__)


def estimate_submission(
    exam: Exam,
    submitted_answers: str,
    difficulties: Sequence[float] | None = None,
    *,
    context: scoring.ScoringContext | None = None,
) -> rasch.RaschEstimate:
    """Bitta o'quvchi javobini Rasch modeli bo'yicha baholaydi.

    Hisoblash `services/scoring.py` da (yagona nuqta): kontekst → item
    natijalari → θ. Rejim (eski A–D harflar yoki MVP: A–F + sonli) kontekstda.

    Args:
        exam: imtihon yozuvi.
        submitted_answers: o'quvchining kanonik javob matni.
        difficulties: `b` lar (berilmasa — imtihondan olinadi); ko'p javobni
            bir marta baholashda qayta ishlatish uchun.
        context: tayyor kontekst (berilmasa — `exam` dan quriladi).

    Raises:
        AnswerKeyError: kalit buzuq bo'lsa.
    """
    ctx = context if context is not None else scoring.ScoringContext.from_exam(exam)
    if difficulties is not None:
        # M1: `b` endi identlik kaliti bo'yicha (`b_by_key`), pozitsiya bo'yicha emas.
        ctx = replace(
            ctx,
            b_by_key={
                str(position): float(value)
                for position, value in enumerate(difficulties, start=1)
            },
        )
    return scoring.estimate_theta(scoring.build_item_results(ctx, submitted_answers), ctx)


def build_estimate(exam: Exam, submitted_answers: str) -> rasch.RaschEstimate:
    """Bitta o'quvchi javobini Rasch modeli bo'yicha baholaydi (qulaylik)."""
    return estimate_submission(exam, submitted_answers)


def _label_position(label: str) -> int:
    """Belgidan pozitsiyani oladi: `"36a"` → `36` (raqam bo'lmasa — `0`)."""
    digits = "".join(char for char in str(label) if char.isdigit())
    return int(digits) if digits else 0


def _legacy_answered_count(canonical: str) -> int:
    """Kanonik matndagi belgilangan javoblar soni (`user_answers`).

    `1A2B...45X|36:12.5` ko'rinishidagi matndan harflar va sonli javoblarni
    sanaydi. Item-level `responses` bilan solishtirish uchun kerak: agar
    autosave to'liq bo'lmasa, item-level manba o'quvchini **kam** baholaydi.
    """
    letters, _, numeric = str(canonical).partition(answer_key.NUMERIC_SECTION_SEPARATOR)
    letter_count = sum(1 for char in letters if char.isalpha() and char.upper() != SKIPPED)
    numeric_count = sum(1 for chunk in numeric.split(",") if chunk.strip())
    return letter_count + numeric_count


async def load_item_level_answers(
    repos: Repositories, attempt_id: int, total_questions: int
) -> str | None:
    """Item-level javoblarni (`responses`) kanonik matnga aylantiradi.

    Oqim: ``repos.responses.current_by_label()`` → har bir savolning **joriy**
    javobi (`is_current = 1`) → kanonik matn (`1A2B…35F|36:12.5` yoki qismli
    `…|36a:√5,36b:3/7`) — ya'ni ``scoring.build_item_results()`` qabul
    qiladigan ko'rinish. Shu sababli baholash qoidasi **bitta joyda** qoladi
    (`form_layout.score_items`).

    Phase 3 Step 3: javob **belgi** (`label`) bo'yicha kalitlanadi — `36a` va
    `36b` bir pozitsiyani (36) bo'lishsa ham **to'qnashmaydi**. Legacy
    (qismsiz) javob avvalgidek int pozitsiya bo'yicha yoziladi (`36` → `36`),
    shu sababli eski imtihonlar natijasi **o'zgarmaydi**.

    Ishlatiladigan maydonlar:
      * `answer_kind` — `option` / `numeric` (savol javob turi);
      * `selected_option` — variant javobi (A–F, 33–35 uchun ham);
      * `numeric_value` va `normalized_answer` — sonli javob (36–45);
      * `capture_status` — `answered` bo'lmasa javob hisobga olinmaydi.

    Qaytaradi:
        Kanonik matn yoki `None` — joriy javoblar umuman bo'lmasa (chaqiruvchi
        eski `user_answers` oqimiga qaytadi).

    Raises:
        answer_key.AnswerKeyError: javoblar bloki formati buzuq bo'lsa.
    """
    by_label = await repos.responses.current_by_label(int(attempt_id))
    if not by_label:
        return None

    total = max(int(total_questions or 0), 0)
    if total == 0:
        return None

    letters = [SKIPPED] * total
    numeric: dict[int | str, Any] = {}

    for label, row in by_label.items():
        # Phase 3 Step 3: javob **belgi** (label) bo'yicha aniqlanadi — `36a` va
        # `36b` bir pozitsiyani (36) bo'lishadi, pozitsiya bo'yicha kalitlashsa
        # ularning biri ikkinchisini bosib ketardi.
        text = str(label).strip()
        try:
            position, part = answer_key.split_label(text)
        except ValueError:
            # Himoya: belgi buzuq bo'lsa (sxema qoidasi bo'yicha bu holat
            # bo'lmasligi kerak) — satr pozitsiyasiga qaytamiz.
            position = int(row.get("position") or _label_position(text))
            part = None
        if not 1 <= position <= total:
            continue
        if str(row.get("capture_status") or "answered") != "answered":
            continue

        kind = str(row.get("answer_kind") or "option")
        if kind == "numeric":
            value = row.get("normalized_answer")
            if value in (None, ""):
                value = row.get("numeric_value")
            if value is None:
                continue
            # Qismli javob kaliti — belgi (`"36a"`); legacy (`part` yo'q) esa
            # avvalgidek int pozitsiya: `36` → `|36:12.5`.
            numeric[form_layout.label_of(position, part) if part else position] = value
        elif kind == "option":
            option = row.get("selected_option")
            if option:
                letters[position - 1] = str(option).upper()
        # `text` turi MVP baholashda qo'llab-quvvatlanmaydi — javobsiz sanaladi.

    return form_layout.build_canonical(letters, numeric)


async def _resolve_answers(
    repos: Repositories,
    exam: Exam,
    submission: ExamSubmission,
    *,
    session: dict[str, Any] | None,
    form_version_id: int | None,
    context: scoring.ScoringContext,
    item_level_context: scoring.ScoringContext | None,
) -> tuple[str, str, dict[str, Any] | None, scoring.ScoringContext]:
    """Urinish uchun javob manbasi (`responses`/`user_answers`) va faol kontekst.

    Bu — `grade_exam` dagi mantiqning **yagona nusxasi**: oddiy baholash ham,
    shrinkaj uchun oldindan hisoblash ham shu funksiyadan foydalanadi.

    Item-level manbada kalit `form_versions` dan olinadi (A–F + sonli), legacy
    manbada — `exams.answer_key` (A–D).
    """
    attempt = None
    if session is not None and form_version_id is not None:
        attempt = await repos.attempts.get_for_user(
            int(session["session_id"]), int(submission.user_id)
        )

    answers = submission.submitted_answers
    source = "user_answers"
    if config.ITEM_LEVEL_GRADING_ENABLED and attempt is not None:
        # Himoya: `responses` to'liq bo'lmasa (autosave uzilgan bo'lsa) item-level
        # manba o'quvchini KAM baholaydi — shuning uchun legacy bilan solishtiramiz
        # va to'liq bo'lmaganda eski manbaga qaytamiz.
        current_count = await repos.responses.count_current(int(attempt["attempt_id"]))
        legacy_count = _legacy_answered_count(str(submission.submitted_answers or ""))
        if current_count > 0 and current_count >= legacy_count:
            item_level = await load_item_level_answers(
                repos, int(attempt["attempt_id"]), exam.total_questions
            )
            if item_level is not None:
                answers, source = item_level, "responses"
        else:
            logger.warning(
                "Item-level javoblar to'liq emas (attempt_id=%s: responses=%d < "
                "legacy=%d) — legacy manba ishlatildi",
                int(attempt["attempt_id"]),
                current_count,
                legacy_count,
            )

    active_context = (
        item_level_context
        if source == "responses" and item_level_context is not None
        else context
    )
    return answers, source, attempt, active_context


async def _apply_shrinkage(
    repos: Repositories,
    exam: Exam,
    submissions: Sequence[ExamSubmission],
    context: scoring.ScoringContext,
    item_level_context: scoring.ScoringContext | None,
    *,
    session: dict[str, Any] | None,
    form_version_id: int | None,
) -> tuple[scoring.ScoringContext, scoring.ScoringContext | None]:
    """`b` larni o'qituvchi bahosi + javob ma'lumoti bo'yicha aralashtiradi.

    Har bir savol uchun `N` (ishlaganlar) va `W` (to'g'ri) ni **barcha**
    urinishlar bo'yicha sanaydi, so'ng `item_statistics.blended_b_map` orqali
    yakuniy `b` ni oladi va kontekstga o'rnatadi. Faqat
    `config.DIFFICULTY_SHRINKAGE_ENABLED` yoqilganda chaqiriladi.
    """
    counts: dict[str, list[int]] = {}
    for submission in submissions:
        answers, _source, _attempt, active = await _resolve_answers(
            repos,
            exam,
            submission,
            session=session,
            form_version_id=form_version_id,
            context=context,
            item_level_context=item_level_context,
        )
        for result in scoring.build_item_results(active, answers):
            key = (result.label or "") or str(result.question_number)
            bucket = counts.setdefault(key, [0, 0])
            bucket[0] += 1
            if result.is_correct:
                bucket[1] += 1

    if not counts:
        return context, item_level_context

    k = float(getattr(config, "DIFFICULTY_SHRINK_K", item_statistics.K_SHRINK))

    def teacher_value(key: str) -> float | None:
        """Kalit bo'yicha o'qituvchi `b` si (topilmasa `None`)."""
        try:
            return context.difficulty_of(key, _label_position(key) or None)
        except scoring.ScoringContextError:
            return None

    blended = dict(context.b_by_key)
    blended.update(
        item_statistics.blended_b_map(
            {key: (pair[0], pair[1]) for key, pair in counts.items()},
            teacher_value,
            k,
        )
    )
    logger.info(
        "Shrinkaj qo'llanildi: exam_id=%s, savollar=%d, K=%s",
        exam.exam_id,
        len(counts),
        k,
    )
    new_context = replace(context, b_by_key=blended)
    new_item_level = (
        replace(item_level_context, b_by_key=blended)
        if item_level_context is not None
        else None
    )
    return new_context, new_item_level


async def grade_exam(
    repos: Repositories,
    exam: Exam,
    *,
    regrade: bool = False,
    snapshot_writer: scoring.ScoringSnapshotWriter | None = None,
) -> int:
    """Imtihon bo'yicha baholanmagan javoblarni hisoblab, bazaga yozadi.

    Baholash `services/scoring.py` orqali bajariladi: har bir javob uchun item
    natijalari quriladi va θ hisoblanadi. Natija **ikki joyga** tushadi:

    1. `user_answers` (θ/scaled/raw) — **har doim**, eski oqim o'zgarmaydi;
    2. `scoring_snapshots` + `scoring_snapshot_items` + `attempts` — **agar**
       shu test kodi uchun item-level sessiya va o'quvchining urinishi mavjud
       bo'lsa (`scoring.DbSnapshotWriter`). `regrade=True` da yangi snapshot
       yakuniy bo'ladi, avvalgisi saqlanib qoladi.

    Javob manbasi (item-level oqim):

        attempt_id → `responses.current_by_label()` → `scoring.build_item_results()`
        → `rasch` → snapshot

    Bu oqim faqat `config.ITEM_LEVEL_GRADING_ENABLED = True` bo'lganda yoqiladi
    (`load_item_level_answers`). Quyidagilardan biri topilmasa — baholash
    **avtomatik** `user_answers.submitted_answers` (legacy) ga qaytadi:
    sessiya yo'q, urinish yo'q yoki joriy javoblar yo'q.

    Snapshot yozilmasa grading **to'xtamaydi**: xatolik logga yoziladi va
    `user_answers` natijasi baribir saqlanadi.

    Args:
        repos: repository konteyneri.
        exam: imtihon yozuvi.
        regrade: True bo'lsa avval hisoblangan natijalar ham qayta hisoblanadi.
        snapshot_writer: snapshot saqlovchi adapter (test/integratsiya uchun).
            Berilmasa — sessiya/urinish bo'yicha avtomatik tanlanadi; item-level
            manzil topilmasa hech narsa yozilmaydi (eski imtihonlar).

    Qaytaradi:
        Baholangan javoblar soni.

    Raises:
        AnswerKeyError: imtihon kaliti buzuq bo'lsa (masalan, bazaga qo'lda
            noto'g'ri yozilgan bo'lsa).
    """
    if regrade:
        submissions = await repos.answers.list_for_exam(exam.exam_id)
    else:
        submissions = await repos.answers.list_ungraded(exam.exam_id)

    context = scoring.ScoringContext.from_exam(exam)
    scoring.validate_context(context)  # kalit buzuq bo'lsa — shu yerda to'xtaydi

    # Item-level manzil: shu test kodi uchun sessiya bo'lsa (item-level oqim),
    # javoblar `responses` dan o'qilishi va snapshot yozilishi mumkin. Eski
    # imtihonlarda sessiya bo'lmaydi — shunda faqat `user_answers` oqimi.
    session = await repos.sessions.get_by_test_code(exam.test_code)
    form_version_id = (
        int(session["form_version_id"])
        if session is not None and session.get("form_version_id")
        else None
    )
    computed_by = "regrade" if regrade else "system"

    # Item-level kalit: forma versiyasidagi kalit legacy `exams.answer_key` dan
    # farq qilishi mumkin (MVP kaliti: A–F + sonli blok). Kalit buzuq bo'lsa —
    # legacy kalit ishlatiladi (grading to'xtamaydi).
    item_level_context: scoring.ScoringContext | None = None
    if form_version_id is not None:
        form_version = await repos.forms.get_version(form_version_id)
        form_key = str((form_version or {}).get("answer_key") or "")
        if form_key:
            candidate = context.with_answer_key(form_key)
            try:
                scoring.validate_context(candidate)
            except answer_key.AnswerKeyError:
                logger.exception(
                    "Item-level kalit buzuq — legacy kalit ishlatiladi "
                    "(form_version_id=%s)",
                    form_version_id,
                )
            else:
                item_level_context = candidate

    # Shrinkaj (agar yoqilgan bo'lsa): `b` larni javob ma'lumoti bilan aralashtiramiz
    # (o'qituvchi bahosi — kichik N uchun tayanch). `b` o'zgarsa, kontekst yangilanadi.
    if config.DIFFICULTY_SHRINKAGE_ENABLED and submissions:
        context, item_level_context = await _apply_shrinkage(
            repos,
            exam,
            submissions,
            context,
            item_level_context,
            session=session,
            form_version_id=form_version_id,
        )

    rows: list[tuple[float, float, int, int]] = []
    for submission in submissions:
        # Javob manbasi va faol kontekst (item-level yoki legacy) — yagona
        # nusxa `_resolve_answers` da (shrinkaj ham shundan foydalanadi).
        answers, source, attempt, active_context = await _resolve_answers(
            repos,
            exam,
            submission,
            session=session,
            form_version_id=form_version_id,
            context=context,
            item_level_context=item_level_context,
        )

        results = scoring.build_item_results(active_context, answers)
        estimate = scoring.estimate_theta(results, active_context)
        rows.append(
            (
                round(estimate.theta, 4),
                round(estimate.scaled_score, 2),
                estimate.raw_score,
                int(submission.submission_id or 0),
            )
        )
        logger.debug(
            "Baholash manbasi: exam_id=%s, user_id=%s → %s (xom ball=%d)",
            exam.exam_id,
            submission.user_id,
            source,
            estimate.raw_score,
        )

        writer = snapshot_writer
        if writer is None and attempt is not None and form_version_id is not None:
            writer = scoring.DbSnapshotWriter(
                repos,
                attempt_id=int(attempt["attempt_id"]),
                form_version_id=form_version_id,
                session_id=int(session["session_id"]),
                computed_by=computed_by,
            )
        if writer is None:
            continue

        # Snapshot yozilmasa ham grading to'xtamaydi — xatolik logga tushadi
        # (`user_answers` natijasi baribir saqlanadi).
        try:
            await writer.write(
                scoring.build_scoring_snapshot(active_context, results, estimate)
            )
        except Exception:
            logger.exception(
                "Snapshot yozilmadi: exam_id=%s, user_id=%s",
                exam.exam_id,
                submission.user_id,
            )

    await repos.answers.save_scores(rows)
    await repos.exams.mark_graded(exam.exam_id, exam_service.now_db())
    logger.info(
        "Imtihon baholandi: exam_id=%s, javoblar=%d, savollar=%d",
        exam.exam_id,
        len(rows),
        exam.total_questions,
    )
    return len(rows)


async def grade_pending(repos: Repositories) -> int:
    """Muddati tugagan, ammo baholanmagan imtihonlarni baholaydi.

    Qaytaradi: jami baholangan javoblar soni.
    """
    exams = await repos.exams.list_pending_grading(exam_service.now_db())
    graded = 0
    for exam in exams:
        try:
            graded += await grade_exam(repos, exam)
        except Exception:  # bitta buzuq imtihon butun siklini to'xtatmasin
            logger.exception("Imtihonni baholashda xatolik: exam_id=%s", exam.exam_id)
    return graded


async def grading_loop(repos: Repositories, interval: int | None = None) -> None:
    """Fon vazifasi: har `interval` sekundda baholanishi kerak bo'lgan imtihonlarni tekshiradi.

    `main.py` da `asyncio.create_task(...)` orqali ishga tushiriladi va bot
    to'xtaganda `task.cancel()` bilan to'xtatiladi.
    """
    delay = int(interval or config.GRADING_INTERVAL)
    logger.info("Baholash fon vazifasi ishga tushdi (har %d sekundda)", delay)
    while True:
        try:
            graded = await grade_pending(repos)
            if graded:
                logger.info("Fon baholash: %d ta javob hisoblandi", graded)
        except asyncio.CancelledError:
            logger.info("Baholash fon vazifasi to'xtatildi")
            raise
        except Exception:  # sikl hech qachon to'xtab qolmasligi kerak
            logger.exception("Baholash siklida kutilmagan xatolik")
        await asyncio.sleep(delay)


async def ensure_graded(repos: Repositories, exam: Exam) -> Exam:
    """Zaxira baholash: `end_time` o'tgan bo'lsa natijani o'sha zahoti hisoblaydi.

    Bu fon vazifasi ishlamay qolgan holatda ham o'quvchi natijani ko'rishi
    uchun kerak (API qatlami chaqiradi).
    """
    if exam.graded_at is not None or exam.end_time > exam_service.now_db():
        return exam

    await grade_exam(repos, exam)
    refreshed = await repos.exams.get(exam.exam_id)
    return refreshed or exam


def _report_item(result: scoring.ItemScoreResult, theta: float) -> dict[str, Any]:
    """Hisobotdagi bitta savol yozuvi (Web App «Natijalar» oynasi uchun).

    Qismli savolda (`36a`, `36b`) `label` maydoni qo'shiladi — shu bilan ikki
    qism bir pozitsiyani (36) bo'lishsa ham alohida ko'rinadi. Qismsiz
    (legacy) savollarda maydon **qo'shilmaydi**, ya'ni eski hisobot o'zgarmaydi.
    """
    item: dict[str, Any] = {
        "number": result.question_number,
        "answer_type": result.answer_type.value,
        "difficulty": round(result.difficulty, 3),
        "difficulty_label": rasch.difficulty_label(result.difficulty),
        "correct_answer": result.correct_answer,
        "given_answer": result.given_answer,
        "is_correct": result.is_correct,
        "score_awarded": round(result.score_awarded, 4),
        "probability": round(rasch.probability(theta, result.difficulty), 4),
    }
    label = result.label or ""
    if label and label != str(result.question_number):
        item["label"] = label
    return item


def build_report(exam: Exam, submission: ExamSubmission) -> dict[str, Any]:
    """Bitta javob uchun batafsil hisobot (Web App "Natijalar" oynasi uchun).

    Diqqat: hisobot javoblar kalitini ochib beradi — shu sababli uni faqat
    `result_time` kelgandan keyin chaqirish kerak (API qatlami tekshiradi).
    """
    context = scoring.ScoringContext.from_exam(exam)
    results = scoring.build_item_results(context, submission.submitted_answers)
    theta = float(submission.theta or 0.0)

    info = rasch.information(theta, scoring.item_responses(results, context))
    standard_error = (1.0 / math.sqrt(info)) if info > rasch.EPS else None
    scaled_error = standard_error * config.scaled_span() if standard_error else None
    scaled_score = float(submission.scaled_score or 0.0)

    scaled_interval: tuple[float, float] | None = None
    if scaled_error is not None:
        delta = 1.96 * scaled_error
        scaled_interval = (
            round(max(config.SCALED_CAP_MIN, scaled_score - delta), 2),
            round(min(config.SCALED_CAP_MAX, scaled_score + delta), 2),
        )

    items: list[dict[str, Any]] = [
        _report_item(result, theta) for result in results
    ]

    # Algebra / geometriya bo'limlari (pozitsiya bo'yicha; `services/subjects.py`).
    subject_scores = subjects.summarize(
        (result.question_number, result.is_correct) for result in results
    )
    # Har bir fan uchun Rasch balli (0–91) — natija bilan bir shkalada.
    subject_balls = subjects.scaled_scores(
        (result.question_number, result.is_correct, result.difficulty)
        for result in results
    )

    return {
        "exam_id": exam.exam_id,
        "title": exam.title,
        "total_questions": exam.total_questions,
        "raw_score": int(submission.raw_score or 0),
        "theta": round(theta, 4),
        "standard_error": round(standard_error, 4) if standard_error else None,
        "scaled_score": round(scaled_score, 2),
        "scaled_error": round(scaled_error, 2) if scaled_error else None,
        "scaled_interval": scaled_interval,
        "ability_level": rasch.ability_level(scaled_score),
        "advice": rasch.level_advice(scaled_score),
        "submitted_at": submission.submitted_at,
        "subjects": subject_scores,
        "subject_balls": subject_balls,
        "items": items,
    }
