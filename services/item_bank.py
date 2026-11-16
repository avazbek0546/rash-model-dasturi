"""Rasch item banki: per-item `b` qiymatlarini yuklash va tekshirish.

Item bank — bu testning **kalibrlangan** qiyinchiliklar to'plami:

    {"1": -1.649, "2": -2.081, ..., "35": 0.560,
     "36a": 0.135, "36b": 2.142, ..., "45b": 3.184}

Bank `exams.difficulty_logits` ga JSON obyekt sifatida yoziladi (yoki 55
qiymatli massiv sifatida). `services.exam_service.b_by_key()` uni o'qiydi va
`ScoringContext` per-item `b` bilan ishlaydi. Per-item kalitlar (`36a`, `36b`)
bo'lsa `config.THETA_METHOD="auto"` avtomatik **EAP** ni tanlaydi.

Bu modul faqat **ma'lumot** bilan ishlaydi: hech qanday DB yoki tarmoq yo'q.
Yuklash uchun `scripts/load_item_bank.py` dan foydalaning.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from services import form_layout

#: Standart item soni (45 pozitsiya: 35 variant + 20 qism = 55 item).
DEFAULT_TOTAL_QUESTIONS: int = 45


class ItemBankError(ValueError):
    """Item bank fayli buzuq yoki noto'g'ri."""


def labels_for(total_questions: int = DEFAULT_TOTAL_QUESTIONS) -> list[str]:
    """Item belgilari: `1..35`, `36a..45b` (qismlar alohida)."""
    total = max(int(total_questions or 0), 0)
    labels: list[str] = []
    for position in range(1, total + 1):
        for part in form_layout.parts_of(position):
            labels.append(form_layout.label_of(position, part or None))
    return labels


@dataclass(frozen=True, slots=True)
class ItemBank:
    """Bitta testning kalibrlangan item banki."""

    test_code: str
    b_by_label: Mapping[str, float]
    model: str = "rasch_1pl"
    theta_method: str = "eap"
    prior_sd: float | None = None
    source: str = ""
    #: Qo'shimcha metadata (o'zgartirilmaydi, faqat saqlanadi).
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.test_code or "").strip():
            raise ItemBankError("Item bankda `test_code` bo'sh.")
        cleaned: dict[str, float] = {}
        for key, value in self.b_by_label.items():
            label = str(key).strip()
            if not label:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ItemBankError(f"`{label}` uchun b son emas: {value!r}") from exc
            if not math.isfinite(number):
                raise ItemBankError(f"`{label}` uchun b chekli son emas: {value!r}")
            cleaned[label] = number
        if not cleaned:
            raise ItemBankError("Item bankda hech qanday b qiymati yo'q.")
        if self.prior_sd is not None:
            sd = float(self.prior_sd)
            if not math.isfinite(sd) or sd <= 0:
                raise ItemBankError(f"prior_sd musbat chekli son bo'lishi kerak: {sd!r}")
        object.__setattr__(self, "b_by_label", cleaned)

    @property
    def item_count(self) -> int:
        return len(self.b_by_label)

    def b_json(self) -> str:
        """`exams.difficulty_logits` uchun JSON obyekt satri."""
        return json.dumps(
            {label: round(float(value), 6) for label, value in self.b_by_label.items()},
            ensure_ascii=False,
            sort_keys=True,
        )

    def validate_labels(self, total_questions: int = DEFAULT_TOTAL_QUESTIONS) -> None:
        """Bankdagi belgilar shu test strukturasiga mosligini tekshiradi.

        Raises:
            ItemBankError: notanish belgi yoki yetishmayotgan item bo'lsa.
        """
        expected = labels_for(total_questions)
        expected_set = set(expected)
        unknown = sorted(set(self.b_by_label) - expected_set)
        if unknown:
            raise ItemBankError(
                "Item bankda notanish belgilar: " + ", ".join(unknown[:10])
            )
        missing = [label for label in expected if label not in self.b_by_label]
        if missing:
            raise ItemBankError(
                "Item bankda yetishmayotgan itemlar: " + ", ".join(missing[:10])
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ItemBank:
        """JSON obyektidan item bank quradi."""
        if not isinstance(data, Mapping):
            raise ItemBankError("Item bank JSON obyekt bo'lishi kerak.")
        raw_b = data.get("b_by_label") or data.get("b") or {}
        if not isinstance(raw_b, Mapping):
            raise ItemBankError("`b_by_label` obyekt bo'lishi kerak.")
        known = {
            "test_code",
            "b_by_label",
            "b",
            "model",
            "theta_method",
            "prior_sd",
            "source",
        }
        extra = {key: value for key, value in data.items() if key not in known}
        return cls(
            test_code=str(data.get("test_code") or ""),
            b_by_label=raw_b,
            model=str(data.get("model") or "rasch_1pl"),
            theta_method=str(data.get("theta_method") or "eap").lower(),
            prior_sd=(None if data.get("prior_sd") is None else float(data["prior_sd"])),
            source=str(data.get("source") or ""),
            extra=extra,
        )


def load_item_bank(path: Path | str) -> ItemBank:
    """Item bank JSON faylini o'qiydi.

    Raises:
        ItemBankError: fayl topilmasa, JSON buzuq bo'lsa yoki b qiymatlari
            noto'g'ri bo'lsa.
    """
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ItemBankError(f"Item bank faylini o'qib bo'lmadi: {source} ({exc})") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ItemBankError(f"Item bank JSON buzuq: {source} ({exc})") from exc
    return ItemBank.from_dict(data)


def find_item_bank(directory: Path | str, test_code: str) -> Path | None:
    """`data/item_banks/` ichidan test kodi bo'yicha fayl topadi."""
    root = Path(directory)
    code = str(test_code or "").strip().lower()
    if not root.is_dir() or not code:
        return None
    for candidate in sorted(root.glob("*.json")):
        try:
            bank = load_item_bank(candidate)
        except ItemBankError:
            continue
        if bank.test_code.strip().lower() == code:
            return candidate
    return None
