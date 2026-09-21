"""Klaviaturalar paketi (inline + reply)."""

from keyboards.inline import (
    AnalysisCallback,
    AnswerCallback,
    MenuCallback,
    after_test_kb,
    analysis_exams_kb,
    analysis_home_kb,
    analysis_questions_kb,
    answer_kb,
    back_kb,
    menu_kb,
)
from keyboards.reply import (
    ANALYSIS_BUTTON,
    HOME_BUTTON,
    UPLOAD_SOLUTION_BUTTON,
    main_reply_kb,
)

__all__ = [
    "ANALYSIS_BUTTON",
    "AnalysisCallback",
    "AnswerCallback",
    "HOME_BUTTON",
    "MenuCallback",
    "UPLOAD_SOLUTION_BUTTON",
    "after_test_kb",
    "analysis_exams_kb",
    "analysis_home_kb",
    "analysis_questions_kb",
    "answer_kb",
    "back_kb",
    "main_reply_kb",
    "menu_kb",
]