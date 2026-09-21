"""Boshlang'ich savollar to'plami (seed).

Har bir savolda `difficulty_b` — Rasch modelidagi qiyinchilik parametri (logit):

    b = -2.4  → juda oson      (deyarli hamma to'g'ri javob beradi)
    b =  0.0  → o'rtacha       (kuchli va kuchsiz o'quvchi taxminan teng)
    b = +2.3  → juda qiyin     (faqat eng tayyor o'quvchilar yechadi)

Qiyinchilik qiymatlari o'qituvchi tomonidan oldindan belgilanadi (klassik
"muallif bahosi"). Kelajakda ularni real javoblar statistikasi asosida
(calibration) qayta hisoblash mumkin.
"""

from __future__ import annotations

import logging

from database.repository import QuestionRepository

logger = logging.getLogger(__name__)

SEED_QUESTIONS: list[dict] = [
    {
        "question_text": "5 + 7 = ?",
        "option_a": "10",
        "option_b": "11",
        "option_c": "12",
        "option_d": "13",
        "correct_option": "C",
        "difficulty_b": -2.4,
        "topic": "Arifmetika",
    },
    {
        "question_text": "12 × 4 = ?",
        "option_a": "36",
        "option_b": "44",
        "option_c": "48",
        "option_d": "52",
        "correct_option": "C",
        "difficulty_b": -2.0,
        "topic": "Arifmetika",
    },
    {
        "question_text": "45 ÷ 9 = ?",
        "option_a": "4",
        "option_b": "5",
        "option_c": "6",
        "option_d": "9",
        "correct_option": "B",
        "difficulty_b": -1.9,
        "topic": "Arifmetika",
    },
    {
        "question_text": "1/2 + 1/4 = ?",
        "option_a": "2/6",
        "option_b": "3/4",
        "option_c": "1/6",
        "option_d": "2/4",
        "correct_option": "B",
        "difficulty_b": -1.3,
        "topic": "Kasrlar",
    },
    {
        "question_text": "2x + 5 = 13 tenglamaning ildizini toping.",
        "option_a": "x = 3",
        "option_b": "x = 4",
        "option_c": "x = 5",
        "option_d": "x = 9",
        "correct_option": "B",
        "difficulty_b": -1.1,
        "topic": "Tenglamalar",
    },
    {
        "question_text": "200 sonining 15 foizi nechaga teng?",
        "option_a": "15",
        "option_b": "20",
        "option_c": "30",
        "option_d": "45",
        "correct_option": "C",
        "difficulty_b": -0.9,
        "topic": "Foizlar",
    },
    {
        "question_text": "0,25 sonini oddiy kasrga aylantiring.",
        "option_a": "1/2",
        "option_b": "1/3",
        "option_c": "1/4",
        "option_d": "2/5",
        "correct_option": "C",
        "difficulty_b": -0.8,
        "topic": "Kasrlar",
    },
    {
        "question_text": "Uchburchakning ichki burchaklari yig'indisi necha gradus?",
        "option_a": "90",
        "option_b": "180",
        "option_c": "270",
        "option_d": "360",
        "correct_option": "B",
        "difficulty_b": -0.7,
        "topic": "Geometriya",
    },
    {
        "question_text": "(a + b)^2 ifoda qanday yoyiladi?",
        "option_a": "a^2 + b^2",
        "option_b": "a^2 + 2ab + b^2",
        "option_c": "a^2 - 2ab + b^2",
        "option_d": "2a + 2b",
        "correct_option": "B",
        "difficulty_b": -0.4,
        "topic": "Qisqa ko'paytirish",
    },
    {
        "question_text": "x^2 - 5x + 6 = 0 tenglamaning ildizlari qaysi javobda to'g'ri?",
        "option_a": "x = 1 va x = 6",
        "option_b": "x = 2 va x = 3",
        "option_c": "x = -2 va x = -3",
        "option_d": "x = -1 va x = 5",
        "correct_option": "B",
        "difficulty_b": -0.2,
        "topic": "Kvadrat tenglama",
    },
    {
        "question_text": "sin 30° nechaga teng?",
        "option_a": "1/2",
        "option_b": "√3/2",
        "option_c": "√2/2",
        "option_d": "1",
        "correct_option": "A",
        "difficulty_b": 0.2,
        "topic": "Trigonometriya",
    },
    {
        "question_text": "2^x = 32 tenglamadan x ni toping.",
        "option_a": "x = 4",
        "option_b": "x = 5",
        "option_c": "x = 6",
        "option_d": "x = 16",
        "correct_option": "B",
        "difficulty_b": 0.4,
        "topic": "Ko'rsatkichli tenglama",
    },
    {
        "question_text": "log₂ 64 nechaga teng?",
        "option_a": "4",
        "option_b": "5",
        "option_c": "6",
        "option_d": "8",
        "correct_option": "C",
        "difficulty_b": 0.6,
        "topic": "Logarifm",
    },
    {
        "question_text": "Arifmetik progressiya: 3, 7, 11, ... Uning 10-hadi nechaga teng?",
        "option_a": "39",
        "option_b": "41",
        "option_c": "43",
        "option_d": "47",
        "correct_option": "A",
        "difficulty_b": 0.9,
        "topic": "Progressiya",
    },
    {
        "question_text": "x^2 - 4x + 5 = 0 tenglamaning diskriminanti nechaga teng?",
        "option_a": "-4",
        "option_b": "4",
        "option_c": "-36",
        "option_d": "0",
        "correct_option": "A",
        "difficulty_b": 1.1,
        "topic": "Kvadrat tenglama",
    },
    {
        "question_text": "cos 2a ni qaysi formula bilan ifodalash mumkin?",
        "option_a": "cos^2(a) - sin^2(a)",
        "option_b": "1 - 2cos^2(a)",
        "option_c": "2sin^2(a) - 1",
        "option_d": "sin^2(a) + cos^2(a)",
        "correct_option": "A",
        "difficulty_b": 1.3,
        "topic": "Trigonometriya",
    },
    {
        "question_text": "Geometrik progressiyada b₁ = 2, q = 3. Uning b₄ hadi nechaga teng?",
        "option_a": "54",
        "option_b": "18",
        "option_c": "162",
        "option_d": "27",
        "correct_option": "A",
        "difficulty_b": 1.5,
        "topic": "Progressiya",
    },
    {
        "question_text": "∫ x dx integralni hisoblang.",
        "option_a": "x^2 + C",
        "option_b": "x^2/2 + C",
        "option_c": "2x + C",
        "option_d": "x + C",
        "correct_option": "B",
        "difficulty_b": 1.6,
        "topic": "Integral",
    },
    {
        "question_text": "f(x) = x^3 - 3x funksiyaning ekstremum nuqtalari qaysi javobda to'g'ri?",
        "option_a": "x = ±1",
        "option_b": "x = ±3",
        "option_c": "x = 0",
        "option_d": "x = ±2",
        "correct_option": "A",
        "difficulty_b": 2.0,
        "topic": "Hosila",
    },
    {
        "question_text": "lim(x→0) sin x / x limitni hisoblang.",
        "option_a": "0",
        "option_b": "1",
        "option_c": "∞",
        "option_d": "1/2",
        "correct_option": "B",
        "difficulty_b": 2.3,
        "topic": "Limit",
    },
]


async def seed_questions(repo: QuestionRepository) -> int:
    """Savollar bazasi bo'sh bo'lsa, boshlang'ich to'plamni qo'shadi.

    Qaytaradi: qo'shilgan savollar soni (baza to'la bo'lsa — 0).
    """
    existing = await repo.count(only_active=False)
    if existing:
        logger.info("Savollar bazasida %d ta savol bor, seed o'tkazib yuborildi", existing)
        return 0

    await repo.add_many(SEED_QUESTIONS)
    logger.info("%d ta boshlang'ich savol bazaga qo'shildi", len(SEED_QUESTIONS))
    return len(SEED_QUESTIONS)
