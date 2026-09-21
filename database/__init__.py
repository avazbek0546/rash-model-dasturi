"""Ma'lumotlar bazasi qatlami (SQLite + aiosqlite).

- `db.py`         — ulanish va sxema (`Database` klassi). Jadvallar:
                    `users`, `exams`, `user_answers` (yangi platforma) hamda
                    `questions`, `test_results` (arxivdagi mashq rejimi).
- `models.py`     — domen modellari (User, Exam, ExamSubmission, ExamStatus, ...)
- `repository.py` — CRUD amallari (`Repositories` konteyneri: users, questions,
                    results, exams, answers)
- `seed.py`       — eski mashq rejimining boshlang'ich savollari
"""

from database.db import Database
from database.models import Exam, ExamStatus, ExamSubmission, Question, TestResult, User
from database.repository import (
    AlreadySubmittedError,
    ExamAnswerRepository,
    ExamRepository,
    QuestionRepository,
    Repositories,
    ResultRepository,
    UserRepository,
)
from database.seed import seed_questions

__all__ = [
    "AlreadySubmittedError",
    "Database",
    "Exam",
    "ExamAnswerRepository",
    "ExamRepository",
    "ExamStatus",
    "ExamSubmission",
    "Question",
    "QuestionRepository",
    "Repositories",
    "ResultRepository",
    "TestResult",
    "User",
    "UserRepository",
    "seed_questions",
]

