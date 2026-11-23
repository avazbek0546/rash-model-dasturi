"""Standart p (foiz) → b (logit) qiyinchilik xaritasi.

Maqsad
------
Admin har bir imtihon uchun qiyinchilik foizlarini qo'lda kiritmasin:
rasmdagi 55 item bo'yicha `p` (to'g'ri javob foizi) bir marta shu modulda
saqlanadi va har bir item uchun `b` avtomatik hisoblanadi:

    p = percent / 100
    b = ln((1 - p) / p)

`b` `[B_MIN, B_MAX]` (≈ ±4.6) oralig'iga siqiladi — `p = 0` yoki `p = 100`
bo'lganda ham chekli qiymat qoladi. Bu `services/item_statistics.py` dagi
klassik `p → b` modeli bilan bir xil qoida.

Qayerda ishlatiladi
-------------------
* `services/exam_admin.create_exam()` — yangi imtihon yaratilganda
  `difficulty_logits` bo'sh bo'lsa shu xarita JSON obyekt sifatida yoziladi;
* `/new_exam` ustasi — xuddi shunday;
* `scripts/apply_default_difficulty.py` — mavjud imtihonlarga qo'llash uchun;
* `services.exam_service.b_by_key()` — `difficulty_logits` umuman bo'sh
  bo'lsa zaxira sifatida.

Item belgilari (55 ta)
----------------------
`1`..`35` (yopiq savollar) va `36a`, `36b`, ..., `45a`, `45b` (ochiq
savollarning A/B qismlari). Har bir item **o'z** `b` siga ega.

Eslatma
-------
Bu — **klassik** `p → b` o'tkazmasi. `services/calibration.py` dagi JMLE
kalibrlash boshqa usul: u javoblar matritsasidan `b` va `θ` ni birgalikda
baholaydi. Ikkalasi bir vaqtda ishlatilmaydi — aniq per-item `b` (JMLE bank)
bo'lsa, u default xaritadan ustun turadi.
"""

from __future__ import annotations

import json
import math
from types import MappingProxyType
from typing import Final, Mapping

import config

#: `p` shu chegaraga siqiladi (0/100 da `ln` cheksizligidan qochish).
P_MIN: Final[float] = 0.01
P_MAX: Final[float] = 0.99

#: `b` (logit) mutlaq chegarasi — `services/item_statistics.py` bilan bir xil.
B_MIN: Final[float] = -4.6
B_MAX: Final[float] = 4.6

#: Rasmdagi 55 item bo'yicha `p` foizlar (to'g'ri javob berganlar ulushi).
DEFAULT_PERCENT_BY_LABEL: Mapping[str, float] = MappingProxyType(
    {
        "1": 70.0,
        "2": 77.0,
        "3": 76.0,
        "4": 67.0,
        "5": 89.0,
        "6": 81.0,
        "7": 73.0,
        "8": 75.0,
        "9": 58.0,
        "10": 67.0,
        "11": 81.0,
        "12": 68.0,
        "13": 57.0,
        "14": 43.0,
        "15": 70.0,
        "16": 49.0,
        "17": 65.0,
        "18": 53.0,
        "19": 38.0,
        "20": 58.0,
        "21": 64.0,
        "22": 50.0,
        "23": 32.0,
        "24": 84.0,
        "25": 40.0,
        "26": 33.0,
        "27": 33.0,
        "28": 52.0,
        "29": 40.0,
        "30": 40.0,
        "31": 42.0,
        "32": 45.0,
        "33": 60.0,
        "34": 40.0,
        "35": 29.0,
        "36a": 36.0,
        "36b": 10.0,
        "37a": 10.0,
        "37b": 17.0,
        "38a": 31.0,
        "38b": 32.0,
        "39a": 16.0,
        "39b": 13.0,
        "40a": 32.0,
        "40b": 27.0,
        "41a": 8.0,
        "41b": 4.0,
        "42a": 11.0,
        "42b": 7.0,
        "43a": 10.0,
        "43b": 20.0,
        "44a": 9.0,
        "44b": 15.0,
        "45a": 7.0,
        "45b": 5.0,
    }
)


def percent_to_b(percent: float) -> float:
    """Foizni Rasch qiyinchiligiga (`b`, logit) aylantiradi.

    ``b = ln((1 - p) / p)``, bu yerda ``p = percent / 100``. `p` xavfsiz
    oraliqqa siqiladi va natija `[B_MIN, B_MAX]` ga qisiladi.

    >>> round(percent_to_b(90), 4)
    -2.1972
    >>> round(percent_to_b(50), 4)
    0.0
    >>> round(percent_to_b(4), 4)
    3.1781
    """
    value = float(percent)
    if not math.isfinite(value):
        raise ValueError(f"Foiz chekli son bo'lishi kerak: {percent!r}")
    p = min(max(value / 100.0, P_MIN), P_MAX)
    b = math.log((1.0 - p) / p)
    return max(B_MIN, min(B_MAX, b))


#: 55 item uchun tayyor `b` xaritasi (`p → b` formulasi bo'yicha).
DEFAULT_B_BY_LABEL: Mapping[str, float] = MappingProxyType(
    {
        label: percent_to_b(percent)
        for label, percent in DEFAULT_PERCENT_BY_LABEL.items()
    }
)


def _position_of(label: str) -> int:
    """Belgidan pozitsiyani oladi: `"36a"` → `36`."""
    digits = "".join(char for char in str(label) if char.isdigit())
    return int(digits) if digits else 0


def default_b_by_key() -> dict[str, float]:
    """55 item + `36`..`45` pozitsiya zaxiralari.

    * `1`..`35`, `36a`..`45b` — har bir item uchun o'z `b` si;
    * `36`..`45` — qismlar `b` larining o'rtachasi (eski 45 pozitsiyali
      imtihonlar uchun zaxira; yangi 55 itemli oqimda ishlatilmaydi).
    """
    result: dict[str, float] = dict(DEFAULT_B_BY_LABEL)
    for position in range(36, 46):
        values = [
            result[f"{position}{part}"]
            for part in ("a", "b")
            if f"{position}{part}" in result
        ]
        if values:
            result[str(position)] = sum(values) / len(values)
    return result


def default_position_logits(total_questions: int) -> list[float]:
    """`1..total` pozitsiyalar uchun `b` ro'yxati (FormBuilder uchun).

    `36`..`45` pozitsiyalari qismlar `b` larining o'rtachasini oladi —
    shu bilan item-level forma yaratishda (u 45 pozitsiyali ro'yxat kutadi)
    har bir pozitsiya uchun mantiqiy qiymat beriladi. `FormBuilder` o'z
    navbatida `±config.THETA_BOUND` ichidagi logitlarni kutadi, shu sababli
    natija shu chegaraga qisiladi.

    Baholashning o'zi `exams.difficulty_logits` dagi to'liq 55 itemli
    xaritadan foydalanadi — u yerda qisqartirish yo'q.
    """
    total = max(int(total_questions or 0), 0)
    if total <= 0:
        return []
    by_key = default_b_by_key()
    bound = abs(float(config.THETA_BOUND))
    return [
        max(-bound, min(bound, float(by_key.get(str(position), 0.0))))
        for position in range(1, total + 1)
    ]


def default_difficulty_json() -> str:
    """`exams.difficulty_logits` uchun 55 itemli JSON obyekt.

    Faqat item belgilari (`1`..`35`, `36a`..`45b`) yoziladi; pozitsiya
    zaxiralari (`36`..`45`) kerak bo'lganda `b_by_key()` o'zi qo'shadi.
    """
    payload = {
        label: round(float(value), 6)
        for label, value in DEFAULT_B_BY_LABEL.items()
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
