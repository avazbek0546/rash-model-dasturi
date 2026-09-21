"""Test jarayonini boshqarish (test sessiyalari).

Sessiyalar xotirada (RAM) saqlanadi: bot qayta ishga tushsa, tugallanmagan
testlar bekor bo'ladi. Bu ongli tanlov — SQLite'ga har bir tugma bosishni
yozib borish keraksiz yuklama bo'lardi. Yakuniy natijalar esa albatta
`test_results` jadvaliga saqlanadi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from database.models import SKIPPED, Question
from services import rasch


@dataclass(slots=True)
class TestSession:
    """Bitta o'quvchining joriy test urinishi."""

    user_id: int
    questions: list[Question]
    answers: dict[int, str] = field(default_factory=dict)
    index: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -- holat -----------------------------------------------------------------
    @property
    def total(self) -> int:
        """Testdagi savollar soni."""
        return len(self.questions)

    @property
    def current_question(self) -> Question | None:
        """Navbatdagi savol (test tugagan bo'lsa — None)."""
        if 0 <= self.index < self.total:
            return self.questions[self.index]
        return None

    @property
    def position(self) -> int:
        """Joriy savolning tartib raqami (1 dan boshlab)."""
        return min(self.index + 1, self.total)

    @property
    def answered_count(self) -> int:
        """Javob berilgan savollar soni."""
        return len(self.answers)

    @property
    def correct_count(self) -> int:
        """To'g'ri javoblar soni (raw score)."""
        return sum(
            1 for question in self.questions if question.is_correct(
                self.answers.get(question.question_id)
            )
        )

    @property
    def skipped_count(self) -> int:
        """"Bilmayman" bosilgan yoki javobsiz qolgan savollar soni."""
        return sum(
            1
            for question in self.questions
            if self.answers.get(question.question_id, SKIPPED).upper() == SKIPPED
        )

    @property
    def is_finished(self) -> bool:
        """Barcha savollarga javob berildimi?"""
        return self.index >= self.total

    def progress_bar(self, width: int = 10) -> str:
        """Vizual progress: masalan ▰▰▰▱▱▱▱▱▱▱."""
        filled = int(round(width * self.answered_count / self.total)) if self.total else 0
        filled = min(filled, width)
        return "▰" * filled + "▱" * (width - filled)

    # -- amallar ---------------------------------------------------------------
    def register_answer(self, question_id: int, option: str) -> bool:
        """Javobni qayd etadi va keyingi savolga o'tadi.

        Qaytaradi: True — javob qabul qilindi, False — eskirgan/takroriy tugma.
        """
        current = self.current_question
        if current is None or current.question_id != question_id:
            return False
        if question_id in self.answers:
            return False
        self.answers[question_id] = option.upper()
        self.index += 1
        return True

    def build_responses(self) -> list[rasch.ItemResponse]:
        """Rasch modeli uchun javoblar ro'yxati."""
        return rasch.build_responses(self.questions, self.answers)

    def evaluate(self) -> rasch.RaschEstimate:
        """θ (bilim darajasi) va scaled ballni hisoblaydi."""
        return rasch.estimate_theta(self.build_responses())


class TestSessionStore:
    """Barcha faol test sessiyalarini `user_id` bo'yicha saqlovchi oddiy ombor."""

    def __init__(self) -> None:
        self._sessions: dict[int, TestSession] = {}

    def start(self, user_id: int, questions: list[Question]) -> TestSession:
        """Yangi test boshlaydi (eski sessiya bo'lsa — almashtiriladi)."""
        session = TestSession(user_id=user_id, questions=questions)
        self._sessions[user_id] = session
        return session

    def get(self, user_id: int) -> TestSession | None:
        """Faol sessiyani qaytaradi."""
        return self._sessions.get(user_id)

    def pop(self, user_id: int) -> TestSession | None:
        """Sessiyani olib, ombordan o'chiradi."""
        return self._sessions.pop(user_id, None)

    def clear(self, user_id: int) -> None:
        """Sessiyani o'chiradi (natija saqlangandan keyin chaqiriladi)."""
        self._sessions.pop(user_id, None)

    def is_active(self, user_id: int) -> bool:
        """O'quvchida tugallanmagan test bormi?"""
        session = self._sessions.get(user_id)
        return session is not None and not session.is_finished

    def active_count(self) -> int:
        """Faol testlar soni (admin statistikasi uchun)."""
        return len(self._sessions)