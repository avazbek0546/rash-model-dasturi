"""FSM (Finite State Machine) holatlari.

- `RegistrationStates` — birinchi kirishda ism va familiyani so'rash.
- `ExamCreateStates` — o'qituvchi `/new_exam` orqali imtihon yaratish ustasi
  (har bir qadamda bitta ma'lumot so'raladi).
- `TestStates` — eski "mashq rejimi" test jarayoni (arxivda, ishlatilmaydi).
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Birinchi kirishdagi majburiy ro'yxatdan o'tish qadamlari."""

    first_name = State()  # ism
    last_name = State()  # familiya


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


class SolutionUploadStates(StatesGroup):
    """«🎬 Yechimlar» — imtihon panelidan deep-link orqali yuklash holati.

    O'qituvchi panelda savol yonidagi «➕ Yuklash»ni bosganda botga o'tadi va
    bot shu holatga o'tib, **keyingi mediani** (izohsiz) shu savolga bog'laydi.
    """

    awaiting_upload = State()


class AdminManageStates(StatesGroup):
    """`/admins` paneli — yangi adminni qo'shish holati.

    Admin «➕ Admin qo'shish»ni bosgach, bot yangi odamning xabarini
    **forward** qilishni (yoki ID raqamini yozishni) so'raydi.
    """

    waiting_forward = State()
