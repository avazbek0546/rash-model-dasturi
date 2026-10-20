"""Matematik ifodani xavfsiz hisoblash va ekvivalentlikni aniqlash (Phase 2).

Web App dagi parser (`webapp/js/mathpanel.js`) bilan **bir xil grammatika**:
natural javoblarni (`√5`, `3/7`, `π/2`, `|3-8|`, `(1+2)*3`) hisoblash va
matematik jihatdan ekvivalent javoblarni (`3/7 == 6/14`, `√5 == (√20)/2`)
tan olish uchun.

`eval()` ISHLATILMAYDI — faqat oq ro'yxatli rekursiv tushish parseri.

Qo'llab-quvvatlanadi: `+ - * / ^`, qavslar, `|x|`, `√`/`sqrt`, `∛`/`cbrt`,
`π`/`pi`, `%`, o'nlik vergul (`3,5`), yashirin ko'paytma (`2π`, `3(4)`,
`2√5`, `2sin(...)`), `x=5` ko'rinishi (oxirgi `=` dan keyingi qism olinadi).

Maktab funksiyalari (Phase 4): `sin`, `cos`, `tg`, `ctg`, `arcsin`, `arccos`,
`arctg`, `arcctg`, `lg` (asos 10), `ln` (natural), `log` (`lg` bilan bir xil).
Burchak **radianlarda** (wrapper'siz). `deg(...)` / `rad(...)` wrapperlari
esa trig burchak rejimini ifoda ichida belgilaydi (DEG/RAD — Phase 6).
`log_a(b)` yozuvi muvozanatli qavs skani bilan **xavfsiz** ravishda
`log(b)/log(a)` ko'rinishiga o'giriladi (`normalize` ichida).

Bu modul **baholash qoidasining bir qismi** bo'lib, `form_layout.score_items`
va `web/api_v2._answer_payload` tomonidan ishlatiladi. Baholash natijasi
(`is_correct`) orqali Raschga uzatiladi — `rasch.py`/`scoring.py` o'zgarmaydi.
"""

from __future__ import annotations

import math
from typing import Any, Final

_PI: Final[float] = math.pi

# DEG/RAD rejimi (Phase 6): `deg(...)` ichida trig burchak **gradusda**,
# `rad(...)` ichida **radian**; wrapper'siz (legacy) ifoda avvalgidek radian.
# Bu burchak rejimini ifoda matnining o'zi tashiydi -> JS va Python bir xil.
_DEG_PER_RAD: Final[float] = math.pi / 180.0
_RAD_PER_DEG: Final[float] = 180.0 / math.pi

# Minus/tire variantlari (U+2212 minus, U+2013 en-dash, U+2014 em-dash).
_MINUS_CHARS: Final[str] = "\u2212\u2013\u2014"


def normalize(text: Any) -> str:
    """Ifodani hisoblashga tayyorlaydi (JS `normalizeExpression` bilan bir xil).

    ``"x=5"`` → ``"5"``; ``π`` → ``pi``; ``√`` → ``sqrt``; ``∛`` → ``cbrt``;
    ``%`` → ``/100``; ``×``/``·`` → ``*``; ``÷`` → ``/``; ``,`` → ``.``.
    """
    value = str(text or "")
    equal_at = value.rfind("=")
    if equal_at >= 0:
        value = value[equal_at + 1 :]
    for char in _MINUS_CHARS:
        value = value.replace(char, "-")
    value = value.replace("\u00d7", "*").replace("\u00b7", "*")
    value = value.replace("\u00f7", "/")
    value = value.replace(",", ".")
    value = value.replace("\u03c0", "pi")
    value = value.replace("\u221a", "sqrt")
    value = value.replace("\u221b", "cbrt")
    value = value.replace("%", "/100")
    compact = "".join(value.split())
    return _expand_base_log(compact)


def _balance(text: str) -> str:
    """Yopilmagan qavslarni avtomatik yopadi (``√(5`` → ``sqrt(5)``)."""
    opened = text.count("(") - text.count(")")
    return text + ")" * opened if opened > 0 else text


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _acot(value: float) -> float:
    """`arcctg` (kotangens arkk) — qiymat oralig'i ``(0, π)``."""
    return _PI / 2.0 - math.atan(value)


def _expand_base_log_once(text: str) -> str:
    """Bitta o'tishda ``log_<asos>(<argument>)`` ni ``log(arg)/log(asos)`` ga.

    Asos — faqat butun son (raqamlar); argument — qavs ichida. Mos yopiluvchi
    qavs bo'lmasa — oxirigacha argument deb olinadi (``_balance`` xatti-harakati
    bilan bir xil). Asos raqam bo'lmasa yoki ``(`` bo'lmasa — matn tegilmaydi.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("log_", index):
            base_start = index + 4
            base_end = base_start
            while base_end < length and _is_digit(text[base_end]):
                base_end += 1
            if base_end > base_start and base_end < length and text[base_end] == "(":
                depth = 0
                close = base_end
                while close < length:
                    if text[close] == "(":
                        depth += 1
                    elif text[close] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    close += 1
                base = text[base_start:base_end]
                if close < length:
                    argument = text[base_end + 1 : close]
                    out.append(f"(log({argument})/log({base}))")
                    index = close + 1
                else:
                    argument = text[base_end + 1 :]
                    out.append(f"(log({argument})/log({base}))")
                    index = length
                continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _expand_base_log(text: str) -> str:
    """``log_a(b)`` → ``log(b)/log(a)`` (barqaror holatga qadar takrorlanadi).

    Nested yozuv (``log_2(log_2(4))``) keyingi o'tishda almashtiriladi; o'zgarish
    bo'lmasa tsikl to'xtaydi (``log(`` endi ``log_`` bilan boshlanmaydi).
    """
    result = text
    for _ in range(1_000):
        expanded = _expand_base_log_once(result)
        if expanded == result:
            return result
        result = expanded
    return result


class _Parser:
    """Oq ro'yxatli rekursiv tushish parseri (faqat kerakli amallar)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0
        self.deg = False  # `deg(...)` ichida True (gradus); standart — radian

    def _peek(self) -> str:
        return self.text[self.index] if self.index < len(self.text) else ""

    def _starts(self, word: str) -> bool:
        return self.text[self.index : self.index + len(word)] == word

    def _to_rad(self, value: float) -> float:
        """Burchakni hisoblash birligiga o'giradi (deg rejimida gradus→radian)."""
        return value * _DEG_PER_RAD if self.deg else value

    def _from_rad(self, value: float) -> float:
        """Teskari funksiya natijasini rejim birligiga o'giradi (radian→gradus)."""
        return value * _RAD_PER_DEG if self.deg else value

    def _parse_scoped(self, degrees: bool) -> float:
        """`deg(...)`/`rad(...)`: ichidagi ifodani shu burchak rejimida o'qiydi."""
        saved = self.deg
        self.deg = degrees
        try:
            value = self.parse_expression()
        finally:
            self.deg = saved
        if self._peek() != ")":
            raise ValueError("qavs yopilmagan")
        self.index += 1
        return value

    def parse_expression(self) -> float:
        value = self.parse_term()
        for _ in range(10_000):
            char = self._peek()
            if char == "+":
                self.index += 1
                value += self.parse_term()
            elif char == "-":
                self.index += 1
                value -= self.parse_term()
            else:
                break
        return value

    def parse_term(self) -> float:
        value = self.parse_unary()
        for _ in range(10_000):
            char = self._peek()
            if char == "*":
                self.index += 1
                value *= self.parse_unary()
            elif char == "/":
                self.index += 1
                divisor = self.parse_unary()
                if divisor == 0:
                    raise ValueError("nolga bo'lish")
                value /= divisor
            elif (
                char == "("
                or self._starts("pi")
                or self._starts("sqrt")
                or self._starts("cbrt")
                or self._starts("sin")
                or self._starts("cos")
                or self._starts("tg")
                or self._starts("ctg")
                or self._starts("arcsin")
                or self._starts("arccos")
                or self._starts("arctg")
                or self._starts("arcctg")
                or self._starts("lg")
                or self._starts("ln")
                or self._starts("log")
                or self._starts("deg")
                or self._starts("rad")
                or _is_digit(char)
                or char == "."
            ):
                value *= self.parse_unary()  # yashirin ko'paytma: 2pi, 2sin(30)
            else:
                break
        return value

    def parse_unary(self) -> float:
        char = self._peek()
        if char == "-":
            self.index += 1
            return -self.parse_unary()
        if char == "+":
            self.index += 1
            return self.parse_unary()
        if self._starts("sqrt"):
            self.index += 4
            return math.sqrt(self.parse_unary())
        if self._starts("cbrt"):
            self.index += 4
            return math.cbrt(self.parse_unary())
        if self._starts("deg"):
            self.index += 3
            if self._peek() != "(":
                raise ValueError("deg(...) uchun qavs kerak")
            self.index += 1
            return self._parse_scoped(True)
        if self._starts("rad"):
            self.index += 3
            if self._peek() != "(":
                raise ValueError("rad(...) uchun qavs kerak")
            self.index += 1
            return self._parse_scoped(False)
        if self._starts("arcsin"):
            self.index += 6
            return self._from_rad(math.asin(self.parse_unary()))
        if self._starts("arccos"):
            self.index += 6
            return self._from_rad(math.acos(self.parse_unary()))
        if self._starts("arctg"):
            self.index += 5
            return self._from_rad(math.atan(self.parse_unary()))
        if self._starts("arcctg"):
            self.index += 6
            return self._from_rad(_acot(self.parse_unary()))
        if self._starts("sin"):
            self.index += 3
            return math.sin(self._to_rad(self.parse_unary()))
        if self._starts("cos"):
            self.index += 3
            return math.cos(self._to_rad(self.parse_unary()))
        if self._starts("tg"):
            self.index += 2
            return math.tan(self._to_rad(self.parse_unary()))
        if self._starts("ctg"):
            self.index += 3
            return 1.0 / math.tan(self._to_rad(self.parse_unary()))
        if self._starts("lg"):
            self.index += 2
            return math.log10(self.parse_unary())
        if self._starts("ln"):
            self.index += 2
            return math.log(self.parse_unary())
        if self._starts("log"):
            self.index += 3
            return math.log10(self.parse_unary())
        return self.parse_power()

    def parse_power(self) -> float:
        base = self.parse_primary()
        if self._peek() == "^":
            self.index += 1
            return base ** self.parse_unary()  # o'ngga assotsiativ
        return base

    def parse_primary(self) -> float:
        char = self._peek()
        if char == "(":
            self.index += 1
            value = self.parse_expression()
            if self._peek() != ")":
                raise ValueError("qavs yopilmagan")
            self.index += 1
            return value
        if char == "|":
            self.index += 1
            value = abs(self.parse_expression())
            if self._peek() != "|":
                raise ValueError("| yopilmagan")
            self.index += 1
            return value
        if self._starts("pi"):
            self.index += 2
            return _PI
        if _is_digit(char) or char == ".":
            start = self.index
            while self.index < len(self.text) and (
                _is_digit(self.text[self.index]) or self.text[self.index] == "."
            ):
                self.index += 1
            number = float(self.text[start : self.index])
            if not math.isfinite(number):
                raise ValueError("son noto'g'ri")
            return number
        raise ValueError("kutilmagan belgi")


def evaluate(text: Any) -> float | None:
    """Ifodani son sifatida hisoblaydi (hisoblab bo'lmasa — ``None``)."""
    normalized = _balance(normalize(text))
    if not normalized:
        return None
    parser = _Parser(normalized)
    try:
        value = parser.parse_expression()
        if parser.index != len(normalized):
            return None  # hisoblanmagan qoldiq bor
        number = float(value)
    except (ValueError, ZeroDivisionError, OverflowError, ArithmeticError, TypeError):
        return None
    return number if math.isfinite(number) else None


def is_evaluable(text: Any) -> bool:
    """Ifoda hisoblanadimi?"""
    return evaluate(text) is not None


def as_number(value: Any) -> float | None:
    """Son yoki matnni songa aylantiradi (hisoblab bo'lmasa — ``None``)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return evaluate(value)
    return None


def format_number(value: Any) -> str:
    """Sonni kanonik matnga aylantiradi (aniqlikni saqlaydi, ``12.5``, ``3``).

    `form_layout._NUMERIC_RE` bilan mos bo'lishi kerak (≤15 kasr xona).
    """
    number = float(value)
    if number == 0:
        return "0"
    text = f"{number:.15g}"
    if "e" in text or "E" in text:
        text = f"{number:.15f}".rstrip("0").rstrip(".")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def equivalent(
    left: Any,
    right: Any,
    *,
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 0.0,
) -> bool:
    """Ikki qiymat matematik jihatdan ekvivalentmi?

    * ``absolute_tolerance`` — mutlaq farq chegarasi (standart 1e-6);
    * ``relative_tolerance`` — nisbiy chegara (standart 0 → o'chirilgan).

    Ikkala tomon ham ifoda bo'lishi mumkin (``3/7`` va ``6/14``). Hisoblab
    bo'lmasa — ``False``.
    """
    first = as_number(left)
    second = as_number(right)
    if first is None or second is None:
        return False
    if first == second:
        return True
    difference = abs(first - second)
    if difference <= absolute_tolerance:
        return True
    if relative_tolerance > 0:
        scale = max(abs(first), abs(second))
        if scale > 0 and difference <= relative_tolerance * scale:
            return True
    return False

