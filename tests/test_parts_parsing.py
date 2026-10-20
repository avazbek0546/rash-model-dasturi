"""Phase 3, Step 1 regressiya testi: qismli savol belgilarini tahlil qilish.

Faqat TAHLIL qatlami tekshiriladi — baholash/Rasch/grading o'zgarmagan.

Ishga tushirish:
    python tests/test_parts_parsing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import answer_key, form_layout  # noqa: E402


def expect_value_error(func, *args) -> None:
    """Funksiya `ValueError` ko'tarishini tekshiradi."""
    try:
        func(*args)
    except ValueError:
        return
    raise AssertionError(f"ValueError kutilgan edi: {func.__name__}{args!r}")


def check_labels() -> None:
    """split_label / label_of / normalize_part."""
    assert form_layout.split_label("36") == (36, None)
    assert form_layout.split_label("36a") == (36, "a")
    assert form_layout.split_label("36b") == (36, "b")
    print("[OK] split_label: '36' → (36,None), '36a' → (36,'a'), '36b' → (36,'b')")

    assert form_layout.label_of(36, None) == "36"
    assert form_layout.label_of(36, "a") == "36a"
    assert form_layout.label_of(36, "b") == "36b"
    assert form_layout.label_of(36, "") == "36"
    print("[OK] label_of: (36,None) → '36', (36,'a') → '36a', (36,'b') → '36b'")

    assert answer_key.split_label("45b") == (45, "b")
    assert answer_key.label_of(45, "A") == "45a"  # katta harf normallashadi
    assert answer_key.normalize_part(None) == ""
    assert answer_key.normalize_part("B") == "b"
    print("[OK] answer_key primitivlari: normalizatsiya va katta harf")

    # Noto'g'ri belgilar xavfsiz to'xtaydi (ValueError)
    for bad in ("", "   ", "abc", "a36", "36c", "36ab", "36!", "-36", "0", "0a"):
        expect_value_error(answer_key.split_label, bad)
    expect_value_error(answer_key.label_of, 0)
    expect_value_error(answer_key.label_of, 36, "c")
    expect_value_error(answer_key.normalize_part, "z")
    print("[OK] noto'g'ri belgilar → ValueError (xavfsiz)")


def check_legacy_parsing_unchanged() -> None:
    """Legacy kalit/matn tahlili 100% avvalgidek."""
    assert answer_key.parse_numeric_block("1A2B|36:12.5,37:3") == {36: "12.5", 37: "3"}
    assert answer_key.parse_numeric_block("1A2B") == {}
    print("[OK] parse_numeric_block: legacy o'zgarmagan ({36:'12.5', 37:'3'})")

    letters = "".join(
        f"{p}{('ABCD' if p <= 32 else 'ABCDEF')[(p - 1) % (4 if p <= 32 else 6)]}"
        for p in range(1, 36)
    )
    key = f"{letters}|36:12.5"
    parsed_letters, numeric = form_layout.parse_key(key, 36)
    assert len(parsed_letters) == 36, len(parsed_letters)
    assert numeric == {36: 12.5}, numeric
    assert all(isinstance(position, int) for position in numeric)
    print("[OK] form_layout.parse_key: legacy kalit o'zgarmagan (int kalitlar)")


def check_labeled_block() -> None:
    """Label bilan kanonik blokni o'qish/qurish."""
    labeled = "1A2B...|36a:\u221a5,36b:3/7,37a:12,37b:\u03c0/2"
    block = answer_key.parse_labeled_block(labeled)
    assert block == {
        "36a": "\u221a5",
        "36b": "3/7",
        "37a": "12",
        "37b": "\u03c0/2",
    }, block
    print("[OK] parse_labeled_block: 36a:\u221a5, 36b:3/7, 37a:12, 37b:\u03c0/2 (label saqlandi)")

    legacy_block = answer_key.parse_labeled_block("1A2B|36:12.5,37:3")
    assert legacy_block == {"36": "12.5", "37": "3"}, legacy_block
    assert answer_key.parse_labeled_block("1A2B") == {}
    print("[OK] parse_labeled_block: legacy '|36:12.5' → {'36':'12.5'} (label='36')")

    rebuilt = answer_key.format_labeled_block(block)
    assert rebuilt == "36a:\u221a5,36b:3/7,37a:12,37b:\u03c0/2", rebuilt
    assert answer_key.parse_labeled_block("x|" + rebuilt) == block
    assert answer_key.format_labeled_block({}) == ""
    print("[OK] format_labeled_block: label round-trip barqaror")

    for bad in ("1A|36a", "1A|36c:5", "1A|36a:", "1A|:5", "1A|36a:5,36a:6"):
        expect_value_error(answer_key.parse_labeled_block, bad)
    print("[OK] parse_labeled_block: buzuq bloklar → AnswerKeyError")


def main() -> None:
    print("=" * 72)
    print("Phase 3 Step 1: qismli savol belgilarini tahlil qilish")
    print("=" * 72)
    check_labels()
    check_legacy_parsing_unchanged()
    check_labeled_block()
    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
