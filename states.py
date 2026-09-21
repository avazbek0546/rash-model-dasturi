"""FSM (Finite State Machine) holatlari.

- `ExamCreateStates` — o'qituvchi `/new_exam` orqali imtihon yaratish ustasi
  (har bir qadamda bitta ma'lumot so'raladi).
- `TestStates` — eski "mashq rejimi" test jarayoni (arxivda, ishlatilmaydi).
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ExamCreateStates(StatesGroup):
    """`/new_exam` ustasi qadamlari (tartib bilan so'raladi)."""

    title = State()  # imtihon nomi
    test_code = State()  # test kodi (o'quvchi kiritadigan)
    total_questions = State()  # savollar soni
    answer_key = State()  # javoblar kaliti ("1A2B3C...")
    difficulties = State()  # qiyinchilik logitlari (bo'sh → 0.0)
    start_time = State()  # javob qabul qilish boshlanishi
    end_time = State()  # javob qabul qilish tugashi
    result_time = State()  # natijalar e'lon qilinishi
    confirm = State()  # xulosani tasdiqlash


class TestStates(StatesGroup):
    """Eski mashq rejimi holati (arxivlangan oqim uchun saqlanadi)."""

    in_progress = State()
