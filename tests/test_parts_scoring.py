"""Phase 3, Step 3 regressiya testi: label-aware baholash (qismli savollar).

Nima tekshiriladi
-----------------
    1. `36a` va `36b` — **mustaqil** savol (bir pozitsiya 36, ikki natija).
    2. Xom ball 55-item aware: 35 variant + 20 sonli qism (36a…45b).
    3. `√5 ≡ (√20)/2` — ekvivalent shakllar tan olinadi.
    4. `3/7 ≡ 6/14` — kasrlar ekvivalent.
    5. Legacy imtihon 100% o'zgarmaydi (qismsiz kalit ↔ `label = "36"`).
    6. `grading.load_item_level_answers` javoblarni **belgi** bo'yicha yig'adi
       (36a/36b to'qnashmaydi) va 55 savolli kanonik matn beradi.
    7. Phase 1 / Phase 2 / Rasch / Step 1 / Step 2 regressiya testlari
       o'zgarmagan — `subprocess` orqali ishga tushiriladi.

Ishga tushirish:
    python tests/test_parts_scoring.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import SKIPPED, User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import (  # noqa: E402
    answer_key,
    exam_service,
    form_layout,
    grading,
    math_expr,
    scoring,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

TOKEN = "123456789:AAPartsScoringChecks"
ADMIN_ID = 909_000_711
STUDENT = {"id": 909_000_712, "first_name": "Ali", "last_name": "Qismli"}
TOTAL = 45
LEGACY_TOTAL = 36
CODE_PARTS = "SCOR45P"
CODE_LEGACY = "SCOR36L"

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


# ---------------------------------------------------------------------------
# Kalit / javob matnlari
# ---------------------------------------------------------------------------
def key_letters(total: int = 35) -> str:
    """Kalit harflari: 1–32 → A–D, 33–35 → A–F."""
    return "".join(
        f"{position}{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, total + 1)
    )


def part_values() -> dict[str, str]:
    """Qismli kalit qiymatlari — 36a…45b (20 ta qism)."""
    values: dict[str, str] = {"36a": "\u221a5", "36b": "3/7", "37a": "12", "37b": "\u03c0/2"}
    for position in range(38, 46):
        values[f"{position}a"] = str(position)
        values[f"{position}b"] = str(position * 2)
    return values


def part_labels() -> list[str]:
    """Kalitdagi belgilar tartibi: 36a, 36b, 37a, 37b, … 45b."""
    return [f"{position}{part}" for position in range(36, 46) for part in ("a", "b")]


def labeled_parts_key() -> str:
    """Qismli kalit: 35 variant + 20 qism (36a…45b)."""
    return f"{key_letters()}|" + ",".join(
        f"{label}:{value}" for label, value in part_values().items()
    )


def mvp_legacy_key() -> str:
    """Legacy MVP kaliti: 1–35 harflar + `|36:12.5` (qismsiz sonli blok)."""
    return f"{key_letters()}|36:12.5"


def plain_legacy_key(total: int = LEGACY_TOTAL) -> str:
    """Eski (A–D, `|` blokisiz) kalit: `1A2B…36D`."""
    return "".join(f"{p}{'ABCD'[(p - 1) % 4]}" for p in range(1, total + 1))


def submitted(letters: str, numeric: Mapping[str, Any] | None = None) -> str:
    """O'quvchi javoblarining kanonik matni (label bloki bilan)."""
    if not numeric:
        return letters
    block = answer_key.format_labeled_block({str(k): str(v) for k, v in numeric.items()})
    return f"{letters}{answer_key.NUMERIC_SECTION_SEPARATOR}{block}"


def expect_answer_key_error(func: Any, *args: Any) -> None:
    """Funksiya `AnswerKeyError` ko'tarishini tekshiradi."""
    try:
        func(*args)
    except answer_key.AnswerKeyError:
        return
    raise AssertionError(f"AnswerKeyError kutilgan edi: {func.__name__}{args!r}")


def item_context(key: str, total: int, mode: scoring.ScoringMode) -> scoring.ScoringContext:
    """Item-level baholash konteksti (imtihon yozuvisiz — test uchun)."""
    return scoring.ScoringContext(
        exam_id=0,
        total_questions=total,
        answer_key=key,
        b_by_key={str(position): 0.0 for position in range(1, total + 1)},
        mode=mode,
    )



# ---------------------------------------------------------------------------
# 1-qadam: tahlil qatlami (is_labeled_key / parse_labeled_key / build_canonical)
# ---------------------------------------------------------------------------
def check_label_helpers() -> None:
    """`is_labeled_key`, `parse_labeled_key`, `build_canonical`."""
    assert form_layout.is_labeled_key(labeled_parts_key())
    assert form_layout.is_labeled_key("1A2B|36a:\u221a5,36b:3/7")
    assert not form_layout.is_labeled_key(mvp_legacy_key())
    assert not form_layout.is_labeled_key("1A2B|36:12.5,37:3")
    assert not form_layout.is_labeled_key(plain_legacy_key())
    assert not form_layout.is_labeled_key("")
    print("[OK] is_labeled_key: qismli kalit True; `|36:12.5` va qismsiz kalit False")

    letters, values = form_layout.parse_labeled_key(labeled_parts_key(), TOTAL)
    assert len(letters) == TOTAL, len(letters)
    assert letters[0] == "A" and letters[32] == "C" and letters[34] == "E", letters[:35]
    assert letters[35:] == [SKIPPED] * 10, letters[35:]
    assert list(values) == part_labels(), list(values)
    assert abs(values["36a"] - math_expr.evaluate("\u221a5")) < 1e-12
    assert abs(values["36b"] - math_expr.evaluate("3/7")) < 1e-15
    assert values["38a"] == 38.0 and values["38b"] == 76.0, values
    print("[OK] parse_labeled_key: 20 ta belgi (36a\u202645b) alohida o'qildi")

    expect_answer_key_error(form_layout.parse_labeled_key, "1A2B|36a:\u221a5,36c:1", TOTAL)
    expect_answer_key_error(form_layout.parse_labeled_key, "1A2B|36a:\u221a5,36:1", TOTAL)
    expect_answer_key_error(form_layout.parse_labeled_key, "1A2B|46a:1", TOTAL)
    expect_answer_key_error(form_layout.parse_labeled_key, "1A2B|", TOTAL)
    print("[OK] parse_labeled_key: buzuq kalitlar \u2192 AnswerKeyError")

    # build_canonical — int kalit ham, belgi ham qabul qilinadi
    letters = ["A", "B"]
    assert form_layout.build_canonical(letters, {36: "12.5"}) == "1A2B|36:12.5"
    assert form_layout.build_canonical(letters, {"36": "12.5"}) == "1A2B|36:12.5"
    assert form_layout.build_canonical(letters, {"36a": "\u221a5"}) == "1A2B|36a:\u221a5"
    assert (
        form_layout.build_canonical(letters, {"36b": "3/7", "36a": "\u221a5"})
        == "1A2B|36a:\u221a5,36b:3/7"
    )
    assert form_layout.build_canonical(letters, {36: 12.5}) == "1A2B|36:12.5"
    assert answer_key.parse_labeled_block(
        form_layout.build_canonical(letters, {"36a": "\u221a5"})
    ) == {"36a": "\u221a5"}
    assert form_layout.build_canonical(letters, {}) == "1A2B"
    print("[OK] build_canonical: `36 → 36:12.5`, `36a → 36a:√5` (int ham, belgi ham)")


# ---------------------------------------------------------------------------
# 2-qadam: 55-item aware baholash va qismlar mustaqilligi
# ---------------------------------------------------------------------------
def check_parts_scoring() -> None:
    """36a va 36b mustaqil; 35 variant + 20 qism = 55 savol."""
    key = labeled_parts_key()
    letters = key_letters()
    correct = part_values()

    outcomes = form_layout.score_items(key, submitted(letters, correct), TOTAL)
    assert len(outcomes) == 55, len(outcomes)
    labels = [outcome.label for outcome in outcomes]
    assert labels[:35] == [str(p) for p in range(1, 36)], labels[:35]
    assert labels[35:] == part_labels(), labels[35:]
    assert len(set(labels)) == 55, "belgilar takrorlandi"
    assert sum(1 for o in outcomes if o.kind == form_layout.OPTION_KIND) == 35
    assert sum(1 for o in outcomes if o.kind == form_layout.NUMERIC_KIND) == 20
    assert all(o.is_correct for o in outcomes)
    print("[OK] score_items: 35 variant + 20 qism = 55 savol, hammasi to'g'ri (55/55)")

    # Faqat 36a xato — 36b to'g'ri qoladi
    given = dict(correct, **{"36a": "2.5"})
    outcomes = form_layout.score_items(key, submitted(letters, given), TOTAL)
    by_label = {o.label: o for o in outcomes}
    assert len(by_label) == 55
    assert not by_label["36a"].is_correct and by_label["36a"].given_display == "2.5"
    assert by_label["36b"].is_correct
    assert sum(1 for o in outcomes if o.is_correct) == 54
    print("[OK] 36a xato, 36b to'g'ri: 54/55 (qismlar mustaqil)")

    # Faqat 36b xato — 36a to'g'ri qoladi
    given = dict(correct, **{"36b": "0.43"})
    outcomes = form_layout.score_items(key, submitted(letters, given), TOTAL)
    by_label = {o.label: o for o in outcomes}
    assert by_label["36a"].is_correct and not by_label["36b"].is_correct
    assert by_label["36b"].given_display == "0.43"
    assert sum(1 for o in outcomes if o.is_correct) == 54
    print("[OK] 36b xato, 36a to'g'ri: 54/55 (qismlar mustaqil)")

    # 36b javobsiz qolsa ham to'plamda qoladi (Rasch uchun barqaror to'plam)
    given = {label: value for label, value in correct.items() if label != "36b"}
    outcomes = form_layout.score_items(key, submitted(letters, given), TOTAL)
    omitted = {o.label: o for o in outcomes}["36b"]
    assert len(outcomes) == 55
    assert not omitted.is_correct and omitted.given_display is None
    print("[OK] 36b javobsiz: savollar soni 55 da qoladi (javobsiz = noto'g'ri)")


# ---------------------------------------------------------------------------
# 3–4-qadam: matematik ekvivalentlik (√5 va 3/7)
# ---------------------------------------------------------------------------
def check_equivalences() -> None:
    """`√5 ≡ (√20)/2` va `3/7 ≡ 6/14` qismli baholashda ham tan olinadi."""
    key = labeled_parts_key()
    letters = key_letters()
    correct = part_values()

    given = dict(correct, **{"36a": "(\u221a20)/2", "36b": "6/14"})
    outcomes = form_layout.score_items(key, submitted(letters, given), TOTAL)
    by_label = {o.label: o for o in outcomes}
    assert by_label["36a"].is_correct, by_label["36a"]
    assert by_label["36b"].is_correct, by_label["36b"]
    # Ko'rsatiladigan matn 4 xonaga yumaloqlanadi (avvalgi xulq), baholash esa
    # to'liq aniqlikda: `(√20)/2` → 2.23606797749979 ≈ `√5`.
    assert by_label["36a"].given_display == by_label["36a"].correct_display
    assert by_label["36b"].given_display == by_label["36b"].correct_display
    assert sum(1 for o in outcomes if o.is_correct) == 55
    print("[OK] \u221a5 \u2261 (\u221a20)/2 va 3/7 \u2261 6/14 \u2014 ikkala qism to'g'ri (55/55)")

    for label, wrong in (("36a", "2.23"), ("36b", "0.43")):
        given = dict(correct, **{label: wrong})
        outcomes = form_layout.score_items(key, submitted(letters, given), TOTAL)
        by_label = {o.label: o for o in outcomes}
        assert not by_label[label].is_correct, by_label[label]
        assert by_label["36b" if label == "36a" else "36a"].is_correct
    print("[OK] 2.23 (\u221a5 emas) va 0.43 (3/7 emas) rad etildi \u2014 faqat o'sha qism xato")


# ---------------------------------------------------------------------------
# Plan CASE 1–2: faqat 36a/36b bo'lgan kalitda aniq xulq
# ---------------------------------------------------------------------------
def two_part_key() -> str:
    """Kalit: 1–35 harflar + faqat `36a`/`36b` (CASE 1–2 uchun minimal misol)."""
    return f"{key_letters()}|36a:\u221a5,36b:3/7"


def omitted_letters(total: int = 35) -> str:
    """Javob berilmagan variantlar matni (`1X2X…35X`)."""
    return "".join(f"{position}{SKIPPED}" for position in range(1, total + 1))


def check_plan_cases() -> None:
    """CASE 1: `(√20)/2` va `6/14` → ikkalasi to'g'ri. CASE 2: `2.23` va `0.43` → xato."""
    key = two_part_key()

    # CASE 1 — ekvivalent shakllar
    outcomes = form_layout.score_items(
        key, submitted(omitted_letters(), {"36a": "(\u221a20)/2", "36b": "6/14"}), LEGACY_TOTAL
    )
    numeric = {o.label: o for o in outcomes if o.kind == form_layout.NUMERIC_KIND}
    assert set(numeric) == {"36a", "36b"}, sorted(numeric)
    assert numeric["36a"].is_correct, numeric["36a"]
    assert numeric["36b"].is_correct, numeric["36b"]
    assert len(outcomes) == 37, len(outcomes)  # 35 variant (javobsiz) + 36a + 36b
    print("[OK] CASE 1: 36a:(√20)/2 \u2261 √5, 36b:6/14 \u2261 3/7 \u2014 ikkalasi ham correct")

    # CASE 2 — yaqin, lekin ekvivalent emas javoblar
    outcomes = form_layout.score_items(
        key, submitted(omitted_letters(), {"36a": "2.23", "36b": "0.43"}), LEGACY_TOTAL
    )
    numeric = {o.label: o for o in outcomes if o.kind == form_layout.NUMERIC_KIND}
    assert not numeric["36a"].is_correct and not numeric["36b"].is_correct, numeric
    assert numeric["36a"].given_display == "2.23" and numeric["36b"].given_display == "0.43"
    print("[OK] CASE 2: 36a:2.23, 36b:0.43 \u2014 ikkalasi ham incorrect")

    # CASE 5 (baholash qismi) — bir qismning xatosi ikkinchisiga ta'sir qilmaydi
    for wrong_label, wrong, ok_label in (("36a", "2.23", "36b"), ("36b", "0.43", "36a")):
        given = {"36a": "\u221a5", "36b": "3/7"}
        given[wrong_label] = wrong
        outcomes = form_layout.score_items(
            key, submitted(omitted_letters(), given), LEGACY_TOTAL
        )
        numeric = {o.label: o for o in outcomes if o.kind == form_layout.NUMERIC_KIND}
        assert not numeric[wrong_label].is_correct, numeric
        assert numeric[ok_label].is_correct, numeric
    print("[OK] CASE 5: 36a/36b mustaqil baholanadi (biri xato \u2014 ikkinchisi to'g'ri)")


# ---------------------------------------------------------------------------
# CASE 4: legacy `36:12.5` — eski algoritm bilan bayt-bayt bir xil
# ---------------------------------------------------------------------------
def reference_number_text(value: Any) -> str:
    """Step 3 gacha bo'lgan `_number_text` nusxasi (mustaqil etalon)."""
    if isinstance(value, str):
        return form_layout.normalize_numeric(value)
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def reference_legacy_outcomes(
    key_text: str, submitted_text: str, total_questions: int
) -> list[tuple[Any, ...]]:
    """Step 3 dan OLDINGI `score_items` algoritmi (legacy regressiya etaloni).

    Nusxa `services/form_layout.py` ning Step 3 gacha bo'lgan kodidan olingan:
    yangi kod legacy kalit uchun **bayt-bayt** bir xil 5 maydonni berishi shart.
    """
    total = int(total_questions)
    correct_letters, correct_numeric = form_layout.parse_key(key_text, total)
    given_letters = answer_key.parse_submitted(
        submitted_text, total, allowed_options=form_layout.allowed_options(total)
    )
    given_numeric = answer_key.parse_numeric_block(submitted_text)
    sections = form_layout.numeric_positions(total)

    rows: list[tuple[Any, ...]] = []
    for position in range(1, total + 1):
        if position in sections:
            correct_value = correct_numeric.get(position)
            given_value = None
            raw_given = given_numeric.get(position)
            if raw_given is not None:
                given_value = math_expr.evaluate(raw_given)
            rows.append(
                (
                    position,
                    form_layout.NUMERIC_KIND,
                    "\u2014" if correct_value is None else reference_number_text(correct_value),
                    None if given_value is None else reference_number_text(given_value),
                    correct_value is not None
                    and given_value is not None
                    and math_expr.equivalent(
                        given_value,
                        correct_value,
                        absolute_tolerance=config.NUMERIC_ABSOLUTE_TOLERANCE,
                        relative_tolerance=config.NUMERIC_RELATIVE_TOLERANCE,
                    ),
                )
            )
            continue
        correct = correct_letters[position - 1]
        given = given_letters[position - 1]
        rows.append(
            (
                position,
                form_layout.OPTION_KIND,
                correct,
                None if given == SKIPPED else given,
                given != SKIPPED and given == correct,
            )
        )
    return rows


def check_legacy_byte_identical() -> None:
    """CASE 4: yangi kod legacy kalitda eski algoritm bilan bir xil natija beradi."""
    key = mvp_legacy_key()
    cases = (
        submitted(key_letters(), {36: "12.5"}),        # hammasi to'g'ri
        omitted_letters(36),                           # hech narsa javob berilmagan
        "1D" + submitted(key_letters(), {36: "12.5"})[2:],  # 1-savol ataylab xato
        submitted(key_letters(), {36: "12.50"}),       # 12.50 \u2261 12.5
        submitted(key_letters(), {}),                  # sonli javob umuman yo'q
    )
    for given_text in cases:
        expected = reference_legacy_outcomes(key, given_text, LEGACY_TOTAL)
        outcomes = form_layout.score_items(key, given_text, LEGACY_TOTAL)
        assert [tuple(o)[:5] for o in outcomes] == expected, given_text
        assert all(o.label == "" for o in outcomes)
    print("[OK] CASE 4: legacy `|36:12.5` \u2014 5 maydon eski algoritm bilan bir xil (5 holat)")


# ---------------------------------------------------------------------------
# 5-qadam: legacy imtihon 100% o'zgarmaydi
# ---------------------------------------------------------------------------
def check_legacy_unchanged() -> None:
    """Qismsiz kalitlar avvalgidek baholanadi (label = `None`, ya'ni `str(position)`)."""
    # (a) MVP legacy kaliti: `|36:12.5` (qism yo'q)
    key = mvp_legacy_key()
    assert not form_layout.is_labeled_key(key)
    outcomes = form_layout.score_items(key, submitted(key_letters(), {36: "12.5"}), LEGACY_TOTAL)
    assert len(outcomes) == 36, len(outcomes)
    assert [o.position for o in outcomes] == list(range(1, 37))
    assert all(o.label == "" for o in outcomes), [o.label for o in outcomes]
    assert outcomes[-1].is_correct and outcomes[-1].given_display == "12.5"
    print("[OK] legacy `|36:12.5`: 36 natija, label bo'sh (`str(position)`) \u2014 avvalgidek")

    # (b) `|` blokisiz eng eski kalit — faqat LETTERS rejimida baholanadi
    plain = plain_legacy_key()
    legacy_context = item_context(plain, LEGACY_TOTAL, scoring.ScoringMode.LETTERS)
    outcomes = scoring.build_item_results(legacy_context, plain)
    assert len(outcomes) == LEGACY_TOTAL and all(r.is_correct for r in outcomes)
    assert [r.label for r in outcomes] == [str(p) for p in range(1, 37)]
    assert all(r.answer_type is scoring.AnswerType.MCQ4 for r in outcomes)
    wrong = "1D" + plain[2:]  # 1-savol ataylab xato (kalit A bilan boshlanadi)
    outcomes = scoring.build_item_results(legacy_context, wrong)
    assert sum(1 for r in outcomes if r.is_correct) == 35
    print("[OK] legacy `1A2B\u202636D` (LETTERS): 36 natija, xato javob ballni kamaytiradi")

    # (c) build_canonical — legacy matn aynan bir xil
    letters = ["A"] * 35 + [SKIPPED]
    canonical = form_layout.build_canonical(letters, {36: "12.5"})
    assert canonical.endswith("|36:12.5"), canonical
    assert canonical == form_layout.build_canonical(letters, {"36": "12.5"})
    assert form_layout.parse_key(canonical, LEGACY_TOTAL)[1] == {36: 12.5}
    print("[OK] build_canonical: `|36:12.5` matni o'zgarmadi (int kalit)")


# ---------------------------------------------------------------------------
# `build_item_results` — belgi har bir natijaga yoziladi
# ---------------------------------------------------------------------------
def check_item_results_labels() -> None:
    """`ItemScoreResult.label`, turi (`_answer_type`) va Rasch ko'rsatkichlari."""
    context = item_context(labeled_parts_key(), TOTAL, scoring.ScoringMode.ITEM_LEVEL)
    results = scoring.build_item_results(context, submitted(key_letters(), part_values()))

    assert len(results) == 55, len(results)
    assert results[0].label == "1" and results[34].label == "35"
    assert [r.label for r in results[35:]] == part_labels(), [r.label for r in results[35:]]
    assert results[35].question_number == 36 and results[36].question_number == 36
    assert results[35].question_key == "36a" and results[36].question_key == "36b"
    assert results[35].answer_type is scoring.AnswerType.NUMERIC
    assert results[36].answer_type is scoring.AnswerType.NUMERIC
    assert results[0].answer_type is scoring.AnswerType.MCQ4
    assert results[32].answer_type is scoring.AnswerType.MCQ6
    assert all(r.is_correct for r in results)
    print("[OK] build_item_results: 55 natija, 36a/36b belgilari va `numeric` turi saqlandi")

    estimate = scoring.estimate_theta(results, context)
    assert estimate.raw_score == 55 and estimate.total_items == 55, estimate
    print(
        f"[OK] Rasch: xom ball={estimate.raw_score}/{estimate.total_items}, "
        f"\u03b8={estimate.theta:.3f}, ball={estimate.scaled_score:.2f}"
    )

    # Legacy (LETTERS) rejimi — natijalar avvalgidek
    legacy_key = plain_legacy_key()
    legacy_context = item_context(legacy_key, LEGACY_TOTAL, scoring.ScoringMode.LETTERS)
    legacy_results = scoring.build_item_results(legacy_context, legacy_key)
    assert len(legacy_results) == LEGACY_TOTAL
    assert [r.label for r in legacy_results] == [str(p) for p in range(1, LEGACY_TOTAL + 1)]
    assert all(r.answer_type is scoring.AnswerType.MCQ4 for r in legacy_results)
    assert all(r.is_correct for r in legacy_results)
    assert scoring.estimate_theta(legacy_results, legacy_context).raw_score == LEGACY_TOTAL
    print("[OK] legacy (LETTERS) rejimi: 36 natija, barcha tur `mcq4` \u2014 o'zgarmagan")


# ---------------------------------------------------------------------------
# 6-qadam: item-level oqim (`responses` → kanonik matn → baholash)
# ---------------------------------------------------------------------------
def build_init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-parts-scoring",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


HEADERS = {"X-Init-Data": build_init_data(STUDENT)}


def numeric_spec() -> str:
    """`answer_spec` (sonli savol, bo'sh `accepted` — kalit blokda)."""
    return json.dumps({"kind": "numeric", "accepted": [], "tolerance": 1e-6})


def form_questions(with_parts: bool, total: int = TOTAL) -> list[dict]:
    """1–32 (mcq4) + 33–35 (mcq6) + 36…total (sonli; qismli bo'lsa a/b)."""
    questions: list[dict] = []
    for position in range(1, 36):
        options = "ABCD" if position <= 32 else "ABCDEF"
        questions.append(
            {
                "position": position,
                "display_label": str(position),
                "part": "",
                "section_no": 1 if position <= 32 else 2,
                "item_type": "mcq4" if position <= 32 else "mcq6",
                "correct_option": options[(position - 1) % len(options)],
                "options_count": len(options),
                "answer_spec": json.dumps({"kind": "option"}),
                "points": 1.0,
                "difficulty": 0.0,
            }
        )
    for position in range(36, max(total, 35) + 1):
        for part in ("a", "b") if with_parts else ("",):
            questions.append(
                {
                    "position": position,
                    "display_label": f"{position}{part}",
                    "part": part,
                    "section_no": 3,
                    "item_type": "numeric",
                    "correct_option": None,
                    "options_count": 0,
                    "answer_spec": numeric_spec(),
                    "points": 1.0,
                    "difficulty": 0.0,
                }
            )
    return questions


async def start_attempt(client: TestClient, code: str) -> dict:
    """`/api/v2/attempt/start` — urinishni boshlaydi."""
    response = await client.post(
        "/api/v2/attempt/start", json={"test_code": code}, headers=HEADERS
    )
    assert response.status == 200, (code, response.status, await response.text())
    return await response.json()


async def autosave(
    client: TestClient,
    attempt_id: int,
    position: int,
    part: str,
    value: Any,
    seq: int,
    *,
    expression: str | None = None,
    answer_kind: str = "numeric",
) -> dict:
    """`/api/v2/autosave` — bitta javob (idempotent, `client_seq` bilan)."""
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "position": position,
        "part": part,
        "value": value,
        "answer_kind": answer_kind,
        "client_seq": seq,
    }
    if expression is not None:
        body["expression"] = expression
    response = await client.post("/api/v2/autosave", json=body, headers=HEADERS)
    assert response.status == 200, (position, part, response.status, await response.text())
    return await response.json()



def numeric_given() -> dict[str, str]:
    """O'quvchi sonli javoblari: 36a va 36b — ekvivalent shakllarda."""
    given = dict(part_values())
    given["36a"] = "(\u221a20)/2"
    given["36b"] = "6/14"
    return given


async def fill_attempt(
    client: TestClient, attempt_id: int, with_parts: bool, total: int = TOTAL
) -> int:
    """Barcha savollarga to'g'ri javob yozadi va oxirgi `client_seq` ni qaytaradi."""
    seq = 0
    for position in range(1, 36):
        options = "ABCD" if position <= 32 else "ABCDEF"
        seq += 1
        await autosave(
            client,
            attempt_id,
            position,
            "",
            options[(position - 1) % len(options)],
            seq,
            answer_kind="option",
        )
    given = numeric_given() if with_parts else {"36": "12.5"}
    for position in range(36, max(total, 35) + 1):
        for part in ("a", "b") if with_parts else ("",):
            expression = given[f"{position}{part}"]
            value = math_expr.format_number(math_expr.evaluate(expression))
            seq += 1
            await autosave(
                client, attempt_id, position, part, value, seq, expression=expression
            )
    return seq


async def check_db_pipeline(repos: Repositories) -> None:
    """`grading.load_item_level_answers` belgi bo'yicha yig'adi (to'qnashuv yo'q)."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_PARTS)
        attempt_id = int(started["attempt_id"])
        await fill_attempt(client, attempt_id, with_parts=True)

        canonical = await grading.load_item_level_answers(repos, attempt_id, TOTAL)
        assert canonical is not None
        block = answer_key.parse_labeled_block(canonical)
        assert list(block) == part_labels(), list(block)
        assert "36" not in block, block
        assert abs(float(block["36a"]) - math_expr.evaluate("\u221a5")) < 1e-12
        assert abs(float(block["36b"]) - math_expr.evaluate("3/7")) < 1e-12
        print("[OK] load_item_level_answers: 20 ta belgi (36a\u202645b), to'qnashuv yo'q")

        # CASE 5 (saqlash qismi): 36a va 36b — alohida `responses` satrlari
        rows = await repos.responses.current_by_label(attempt_id)
        assert {"36a", "36b"} <= set(rows), sorted(rows)
        assert rows["36a"]["form_item_id"] != rows["36b"]["form_item_id"]
        assert rows["36a"]["part"] == "a" and rows["36b"]["part"] == "b"
        assert float(rows["36a"]["numeric_value"]) != float(rows["36b"]["numeric_value"])
        print("[OK] CASE 5: 36a va 36b alohida saqlanadi (turli form_item_id/qiymat)")

        context = item_context(labeled_parts_key(), TOTAL, scoring.ScoringMode.ITEM_LEVEL)
        results = scoring.build_item_results(context, canonical)
        assert len(results) == 55, len(results)
        assert sum(1 for r in results if r.is_correct) == 55
        estimate = scoring.estimate_theta(results, context)
        assert estimate.raw_score == 55 and estimate.total_items == 55, estimate
        print("[OK] Item-level oqim: 55 savol, xom ball 55 (36a va 36b alohida)")

        # Legacy forma: `36` belgisi o'zgarmaydi
        started = await start_attempt(client, CODE_LEGACY)
        legacy_attempt = int(started["attempt_id"])
        await fill_attempt(client, legacy_attempt, with_parts=False, total=LEGACY_TOTAL)
        legacy_canonical = await grading.load_item_level_answers(
            repos, legacy_attempt, LEGACY_TOTAL
        )
        assert legacy_canonical is not None
        assert answer_key.parse_labeled_block(legacy_canonical) == {"36": "12.5"}
        assert legacy_canonical.endswith("|36:12.5"), legacy_canonical

        legacy_context = item_context(
            mvp_legacy_key(), LEGACY_TOTAL, scoring.ScoringMode.ITEM_LEVEL
        )
        legacy_results = scoring.build_item_results(legacy_context, legacy_canonical)
        assert len(legacy_results) == LEGACY_TOTAL
        assert [r.label for r in legacy_results] == [str(p) for p in range(1, 37)]
        assert sum(1 for r in legacy_results if r.is_correct) == LEGACY_TOTAL
        assert legacy_results[-1].answer_type is scoring.AnswerType.NUMERIC
        assert legacy_results[31].answer_type is scoring.AnswerType.MCQ4
        assert legacy_results[32].answer_type is scoring.AnswerType.MCQ6
        print("[OK] Legacy forma: `|36:12.5` va 36 natija \u2014 avvalgidek (`label='36'`)")


# ---------------------------------------------------------------------------
# 7-qadam: Phase 1 / Phase 2 / Rasch / Step 1 / Step 2 regressiyasi
# ---------------------------------------------------------------------------
REGRESSIONS: tuple[tuple[str, str], ...] = (
    ("Phase 1", "tests/test_expression_preservation.py"),
    ("Phase 2", "tests/test_symbolic_equivalence.py"),
    ("Rasch", "tests/test_rasch.py"),
    ("Step 1", "tests/test_parts_parsing.py"),
    ("Step 2", "tests/test_parts_capture.py"),
    ("Legacy M1", "tests/test_legacy_item_level.py"),
)


def check_regressions() -> None:
    """Oldingi bosqich testlari o'zgarmagan — alohida jarayonda ishga tushiriladi."""
    for name, relative in REGRESSIONS:
        completed = subprocess.run(
            [sys.executable, relative],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=900,
        )
        lines = [
            line.strip()
            for line in (completed.stdout or "").splitlines()
            if line.strip() and set(line.strip()) != {"="}
        ]
        tail = lines[-1] if lines else ""
        assert completed.returncode == 0, (
            f"{name} ({relative}) yiqildi (kod={completed.returncode}).\n"
            f"Oxirgi satr: {tail}\n{completed.stderr[-2000:]}"
        )
        print(f"[OK] {name} regressiyasi: {relative} \u2192 {tail}")


# ---------------------------------------------------------------------------
# Test formalarini yaratish va ishga tushirish
# ---------------------------------------------------------------------------
async def make_form(
    repos: Repositories, code: str, total: int, with_parts: bool, answer_key_text: str
) -> None:
    """Item-level forma + vaqt oynasi (sessiya) yaratadi."""
    parts = part_labels() if with_parts else []
    form_id, _version = await repos.forms.create_full_form(
        title=f"Scoring {code}",
        test_code=code,
        total_questions=total,
        answer_key=answer_key_text,
        questions=form_questions(with_parts, total),
        parts=parts,
        created_by=ADMIN_ID,
    )
    now = exam_service.utc_now()
    await repos.sessions.create(
        form_id=form_id,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        title=f"Sessiya {code}",
        created_by=ADMIN_ID,
    )


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_parts_scoring_"))
    db = Database(tmp_dir / "parts_scoring.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Phase 3 Step 3: label-aware baholash (qismli savollar)")
    print("=" * 72)
    try:
        await repos.users.upsert(
            User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
        )
        await repos.users.upsert(
            User(user_id=STUDENT["id"], full_name="Ali Qismli", username=None)
        )
        await make_form(repos, CODE_PARTS, TOTAL, True, labeled_parts_key())
        await make_form(repos, CODE_LEGACY, LEGACY_TOTAL, False, mvp_legacy_key())

        check_label_helpers()
        check_parts_scoring()
        check_equivalences()
        check_plan_cases()
        check_legacy_unchanged()
        check_legacy_byte_identical()
        check_item_results_labels()
        await check_db_pipeline(repos)
        check_regressions()
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 3 Step 3 muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
