"""Offline mock import uchun repository qatlami.

Faqat 011 migratsiyasida yaratilgan yangi jadvallar bilan ishlaydi.
Mavjud `users` / `user_answers` / `attempts` ga tegmaydi.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Sequence

from database.db import Database
from database.offline_norm import normalize_name, normalize_username

logger = logging.getLogger(__name__)


def _json_flags(flags: Sequence[int]) -> str:
    return json.dumps([1 if int(value) else 0 for value in flags], separators=(",", ":"))


def _load_flags(value: str) -> list[int]:
    try:
        raw = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [1 if int(item) else 0 for item in raw]


class OfflineImportRepository:
    """`offline_import_batches`, `offline_import_rows`, `offline_import_issues`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def next_batch_no(self, exam_id: int) -> int:
        value = await self._db.fetchvalue(
            "SELECT COALESCE(MAX(batch_no), 0) + 1 FROM offline_import_batches WHERE exam_id = ?",
            (int(exam_id),),
            default=1,
        )
        return int(value or 1)

    async def create_batch(
        self,
        *,
        exam_id: int,
        form_version_id: int,
        uploaded_by: int,
        file_name: str,
        file_sha256: str,
        file_size: int,
        template_version: str,
        key_fingerprint: str,
        b_checksum: str,
        b_source: str,
        engine_version: str,
        offline_test_date: str | None = None,
    ) -> int:
        batch_no = await self.next_batch_no(exam_id)
        return await self._db.execute(
            """
            INSERT INTO offline_import_batches (
                exam_id, form_version_id, batch_no, uploaded_by, file_name,
                file_sha256, file_size, status, template_version,
                key_fingerprint, b_checksum, b_source, engine_version,
                offline_test_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(exam_id), int(form_version_id), batch_no, int(uploaded_by),
                file_name, file_sha256, int(file_size), template_version,
                key_fingerprint, b_checksum, b_source, engine_version,
                offline_test_date,
            ),
        )

    async def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM offline_import_batches WHERE batch_id = ?", (int(batch_id),)
        )

    async def list_batches(self, exam_id: int, limit: int = 20) -> list[dict[str, Any]]:
        return await self._db.fetchall(
            """
            SELECT * FROM offline_import_batches
            WHERE exam_id = ? ORDER BY batch_no DESC LIMIT ?
            """,
            (int(exam_id), int(limit)),
        )

    async def active_by_hash(self, exam_id: int, file_sha256: str) -> dict[str, Any] | None:
        return await self._db.fetchone(
            """
            SELECT * FROM offline_import_batches
            WHERE exam_id = ? AND file_sha256 = ?
              AND status IN ('draft', 'validated', 'committed')
            LIMIT 1
            """,
            (int(exam_id), str(file_sha256)),
        )

    async def add_rows(self, batch_id: int, rows: Iterable[dict[str, Any]]) -> None:
        payload = [
            (
                int(batch_id), int(row["row_no"]), str(row["student_code"]),
                str(row["student_code_norm"]), str(row["full_name"]),
                str(row["full_name_norm"]), str(row.get("class_label") or ""),
                row.get("telegram_username"), _json_flags(row.get("flags") or []),
                str(row.get("row_status") or "valid"), row.get("error_code"),
                row.get("error_message"),
            )
            for row in rows
        ]
        if payload:
            await self._db.execute_many(
                """
                INSERT INTO offline_import_rows (
                    batch_id, row_no, student_code, student_code_norm, full_name,
                    full_name_norm, class_label, telegram_username, answers_json,
                    row_status, error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    async def add_issues(self, batch_id: int, issues: Iterable[dict[str, Any]]) -> None:
        payload = [
            (
                int(batch_id),
                None if issue.get("row_no") is None else int(issue["row_no"]),
                issue.get("column_name"), str(issue["code"]),
                str(issue["message"]), str(issue.get("severity") or "error"),
            )
            for issue in issues
        ]
        if payload:
            await self._db.execute_many(
                """
                INSERT INTO offline_import_issues (
                    batch_id, row_no, column_name, code, message, severity
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    async def list_rows(self, batch_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT * FROM offline_import_rows WHERE batch_id = ? ORDER BY row_no",
            (int(batch_id),),
        )
        for row in rows:
            row["flags"] = _load_flags(row.get("answers_json") or "[]")
        return rows

    async def list_issues(
        self, batch_id: int, *, severity: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM offline_import_issues WHERE batch_id = ?"
        params: list[Any] = [int(batch_id)]
        if severity:
            sql += " AND severity = ?"
            params.append(str(severity))
        sql += " ORDER BY COALESCE(row_no, 0), issue_id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return await self._db.fetchall(sql, tuple(params))

    async def mark_validated(
        self, batch_id: int, *, rows_total: int, rows_valid: int, rows_invalid: int
    ) -> None:
        await self._db.execute(
            """
            UPDATE offline_import_batches
            SET status = 'validated', rows_total = ?, rows_valid = ?, rows_invalid = ?,
                validated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE batch_id = ? AND status = 'draft'
            """,
            (int(rows_total), int(rows_valid), int(rows_invalid), int(batch_id)),
        )

    async def commit_batch(
        self, *, batch: dict[str, Any], rows: Sequence[dict[str, Any]], admin_id: int
    ) -> dict[str, int]:
        """Partiyani bitta tranzaksiyada yozadi (xatoda rollback)."""
        conn = self._db.connection
        batch_id = int(batch["batch_id"])
        exam_id = int(batch["exam_id"])
        form_version_id = int(batch["form_version_id"])
        stats = {"participants": 0, "created": 0, "updated": 0, "attempts": 0}
        try:
            await conn.execute("BEGIN IMMEDIATE")
            for row in rows:
                participant_id, created = await self._upsert_participant(conn, exam_id, row)
                stats["participants"] += 1
                stats["created" if created else "updated"] += 1
                attempt_id = await self._insert_attempt(
                    conn, batch_id, exam_id, form_version_id, participant_id, row
                )
                stats["attempts"] += 1
                await self._insert_responses(conn, attempt_id, row)
                await self._upsert_decision(
                    conn, exam_id=exam_id, subject_type="offline_participant",
                    subject_id=participant_id, source="offline", included=1,
                    reason="offline_official", admin_id=admin_id,
                )
                row["participant_id"] = participant_id
                row["offline_attempt_id"] = attempt_id
            await conn.execute(
                """
                UPDATE offline_import_batches
                SET status = 'committed',
                    committed_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE batch_id = ?
                """,
                (batch_id,),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("Offline partiya commit qilinmadi: batch_id=%s", batch_id)
            raise
        return stats

    async def _upsert_participant(
        self, conn: Any, exam_id: int, row: dict[str, Any]
    ) -> tuple[int, bool]:
        cursor = await conn.execute(
            "SELECT participant_id FROM offline_participants WHERE exam_id = ? AND student_code_norm = ?",
            (int(exam_id), str(row["student_code_norm"])),
        )
        found = await cursor.fetchone()
        if found is not None:
            participant_id = int(found[0])
            await conn.execute(
                """
                UPDATE offline_participants
                SET full_name = ?, full_name_norm = ?, class_label = ?,
                    telegram_username = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE participant_id = ?
                """,
                (
                    str(row["full_name"]), str(row["full_name_norm"]),
                    str(row.get("class_label") or ""), row.get("telegram_username"),
                    participant_id,
                ),
            )
            return participant_id, False
        cursor = await conn.execute(
            """
            INSERT INTO offline_participants (
                exam_id, student_code, student_code_norm, full_name, full_name_norm,
                class_label, telegram_username
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(exam_id), str(row["student_code"]), str(row["student_code_norm"]),
                str(row["full_name"]), str(row["full_name_norm"]),
                str(row.get("class_label") or ""), row.get("telegram_username"),
            ),
        )
        return int(cursor.lastrowid or 0), True

    async def _insert_attempt(
        self, conn: Any, batch_id: int, exam_id: int,
        form_version_id: int, participant_id: int, row: dict[str, Any],
    ) -> int:
        score = row["score"]
        cursor = await conn.execute(
            """
            INSERT INTO offline_attempts (
                batch_id, participant_id, exam_id, form_version_id,
                raw_score, total_items, theta, theta_se, scaled_score, level,
                is_extreme, included_in_ranking, status, engine_version,
                b_checksum, b_source, key_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'valid', ?, ?, ?, ?)
            """,
            (
                int(batch_id), int(participant_id), int(exam_id), int(form_version_id),
                int(score.raw_score), int(score.total_items), float(score.theta),
                None if score.theta_se is None else float(score.theta_se),
                float(score.scaled_score), str(score.level),
                1 if score.is_extreme else 0, str(score.engine_version),
                str(score.b_checksum), str(score.b_source), str(score.key_fingerprint),
            ),
        )
        return int(cursor.lastrowid or 0)

    async def _insert_responses(self, conn: Any, attempt_id: int, row: dict[str, Any]) -> None:
        payload = [
            (
                int(attempt_id), int(item["form_item_id"]),
                int(item["item_version_id"]), int(item["position"]),
                str(item["display_label"]), 1 if item["is_correct"] else 0,
                float(item["b_used"]),
            )
            for item in row["responses"]
        ]
        if payload:
            await conn.executemany(
                """
                INSERT INTO offline_responses (
                    offline_attempt_id, form_item_id, item_version_id, position,
                    display_label, is_correct, b_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    async def _upsert_decision(
        self, conn: Any, *, exam_id: int, subject_type: str, subject_id: int,
        source: str, included: int, reason: str, admin_id: int | None,
    ) -> None:
        await conn.execute(
            """
            UPDATE exam_ranking_decisions SET is_active = 0
            WHERE exam_id = ? AND subject_type = ? AND subject_id = ? AND is_active = 1
            """,
            (int(exam_id), subject_type, int(subject_id)),
        )
        await conn.execute(
            """
            INSERT INTO exam_ranking_decisions (
                exam_id, subject_type, subject_id, source, included_in_ranking,
                reason, decided_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(exam_id), subject_type, int(subject_id), source,
                1 if included else 0, reason,
                None if admin_id is None else int(admin_id),
            ),
        )

    async def void_batch(self, *, batch_id: int, admin_id: int, reason: str) -> dict[str, int]:
        conn = self._db.connection
        batch = await self.get_batch(batch_id)
        if batch is None:
            raise ValueError("Import partiyasi topilmadi.")
        if str(batch.get("status")) == "void":
            return {"attempts": 0, "participants": 0}
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "SELECT DISTINCT participant_id FROM offline_attempts WHERE batch_id = ?",
                (int(batch_id),),
            )
            participant_ids = [int(row[0]) for row in await cursor.fetchall()]
            await conn.execute(
                """
                UPDATE offline_attempts
                SET status = 'void', included_in_ranking = 0,
                    exclusion_reason = 'batch_void'
                WHERE batch_id = ?
                """,
                (int(batch_id),),
            )
            for participant_id in participant_ids:
                await conn.execute(
                    """
                    UPDATE exam_ranking_decisions SET is_active = 0
                    WHERE exam_id = ? AND subject_type = 'offline_participant'
                      AND subject_id = ? AND is_active = 1
                    """,
                    (int(batch["exam_id"]), participant_id),
                )
            await conn.execute(
                """
                UPDATE offline_import_batches
                SET status = 'void',
                    voided_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
                    voided_by = ?, void_reason = ?
                WHERE batch_id = ?
                """,
                (int(admin_id), reason, int(batch_id)),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("Offline partiya bekor qilinmadi: batch_id=%s", batch_id)
            raise
        return {"attempts": len(participant_ids), "participants": len(participant_ids)}

    async def delete_batch(self, *, batch_id: int) -> dict[str, int]:
        """Partiyani bazadan butunlay o'chiradi (tarixda qoldirmaydi).

        `offline_import_rows`, `offline_import_issues`, `offline_attempts` va
        `offline_responses` CASCADE bilan o'chadi. Boshqa partiyada attempti
        qolmagan `offline_participants` (va ularning linklari) ham o'chiriladi;
        reyting qarorlari faolsizlantiriladi — keyin ularni
        `ensure_ranking_decisions()` qayta hisoblaydi.
        """
        conn = self._db.connection
        batch = await self.get_batch(batch_id)
        if batch is None:
            raise ValueError("Import partiyasi topilmadi.")
        exam_id = int(batch["exam_id"])
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "SELECT DISTINCT participant_id FROM offline_attempts WHERE batch_id = ?",
                (int(batch_id),),
            )
            participant_ids = [int(row[0]) for row in await cursor.fetchall()]
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM offline_import_rows WHERE batch_id = ?",
                (int(batch_id),),
            )
            rows_total = int((await cursor.fetchone())[0] or 0)
            await conn.execute(
                "DELETE FROM offline_import_batches WHERE batch_id = ?", (int(batch_id),)
            )
            removed_participants = 0
            for participant_id in participant_ids:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM offline_attempts WHERE participant_id = ?",
                    (participant_id,),
                )
                if int((await cursor.fetchone())[0] or 0):
                    continue  # boshqa partiyada ham bor — o'chirilmaydi
                await conn.execute(
                    "DELETE FROM offline_participants WHERE participant_id = ?",
                    (participant_id,),
                )
                removed_participants += 1
            # Reyting qarorlari `ensure_ranking_decisions()` da qayta yoziladi.
            for participant_id in participant_ids:
                await conn.execute(
                    """
                    UPDATE exam_ranking_decisions SET is_active = 0
                    WHERE exam_id = ? AND subject_type = 'offline_participant'
                      AND subject_id = ? AND is_active = 1
                    """,
                    (exam_id, participant_id),
                )
            await conn.execute(
                """
                UPDATE exam_ranking_decisions SET is_active = 0
                WHERE exam_id = ? AND subject_type = 'telegram_user' AND is_active = 1
                """,
                (exam_id,),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("Offline partiya o'chirilmadi: batch_id=%s", batch_id)
            raise
        return {
            "rows": rows_total,
            "attempts": len(participant_ids),
            "participants": removed_participants,
        }


class OfflineParticipantRepository:
    """`offline_participants` va `offline_participant_links`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, participant_id: int) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM offline_participants WHERE participant_id = ?",
            (int(participant_id),),
        )

    async def get_by_code(self, exam_id: int, code_norm: str) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM offline_participants WHERE exam_id = ? AND student_code_norm = ?",
            (int(exam_id), str(code_norm)),
        )

    async def list_for_exam(self, exam_id: int) -> list[dict[str, Any]]:
        return await self._db.fetchall(
            """
            SELECT * FROM offline_participants
            WHERE exam_id = ? ORDER BY class_label, full_name, student_code
            """,
            (int(exam_id),),
        )

    async def list_confirmed_links(self, exam_id: int) -> list[dict[str, Any]]:
        return await self._db.fetchall(
            """
            SELECT p.*, l.user_id AS linked_user_id, l.link_id
            FROM offline_participants p
            JOIN offline_participant_links l
              ON l.participant_id = p.participant_id
             AND l.status = 'confirmed' AND l.revoked_at IS NULL
            WHERE p.exam_id = ?
            ORDER BY p.class_label, p.full_name
            """,
            (int(exam_id),),
        )

    async def set_suggestion(
        self, participant_id: int, *, user_id: int | None, status: str,
        method: str, confidence: float | None,
    ) -> None:
        await self._db.execute(
            """
            UPDATE offline_participants
            SET matched_user_id = ?, match_status = ?, match_method = ?,
                match_confidence = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE participant_id = ?
            """,
            (
                None if user_id is None else int(user_id), status, method,
                None if confidence is None else float(confidence), int(participant_id),
            ),
        )

    async def candidate_users(self, participant: dict[str, Any]) -> list[dict[str, Any]]:
        # Taxminiy mos foydalanuvchilar (avtomatik bog'lash emas).
        by_username, by_name = await self.candidate_index()
        username = normalize_username(participant.get("telegram_username"))
        if username:
            rows = by_username.get(username.casefold(), [])
            if rows:
                return rows
        return by_name.get(str(participant.get("full_name_norm") or ""), [])

    async def candidate_index(
        self, *, limit: int = 10000
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        """Foydalanuvchilarni username va normallashtirilgan ism bo'yicha indekslaydi.

        Katta guruh import qilinganda har bir o'quvchi uchun alohida SQL
        so'rovi yubormaslik uchun bir marta o'qiladi. Qaytaradi:
        `(username_index, name_index)`.
        """
        rows = await self._db.fetchall(
            """
            SELECT u.user_id, u.full_name, u.username, p.first_name, p.last_name
            FROM users u LEFT JOIN user_profiles p ON p.user_id = u.user_id
            ORDER BY u.user_id LIMIT ?
            """,
            (int(limit),),
        )
        by_username: dict[str, list[dict[str, Any]]] = {}
        by_name: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            user_id = int(row["user_id"])
            username = normalize_username(row.get("username"))
            if username:
                by_username.setdefault(username.casefold(), []).append(
                    {**row, "method": "username", "confidence": 0.95}
                )
            name_item = {**row, "method": "name_class", "confidence": 0.7}
            names = [str(row.get("full_name") or "")]
            if row.get("first_name") or row.get("last_name"):
                names.append(
                    f"{row.get('first_name') or ''} {row.get('last_name') or ''}"
                )
            seen: set[str] = set()
            for name in names:
                key = normalize_name(name)
                if not key or key in seen:
                    continue
                seen.add(key)
                bucket = by_name.setdefault(key, [])
                if all(int(item["user_id"]) != user_id for item in bucket):
                    bucket.append(name_item)
        return by_username, by_name

    async def confirm_link(
        self, *, participant_id: int, user_id: int, admin_id: int,
        method: str = "manual", confidence: float | None = None,
    ) -> None:
        conn = self._db.connection
        try:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                """
                UPDATE offline_participant_links
                SET status = 'revoked',
                    revoked_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE participant_id = ? AND status = 'confirmed' AND revoked_at IS NULL
                """,
                (int(participant_id),),
            )
            await conn.execute(
                """
                UPDATE offline_participants
                SET matched_user_id = ?, match_status = 'confirmed',
                    match_method = ?, match_confidence = ?, confirmed_by = ?,
                    confirmed_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE participant_id = ?
                """,
                (
                    int(user_id), method,
                    None if confidence is None else float(confidence),
                    int(admin_id), int(participant_id),
                ),
            )
            await conn.execute(
                """
                INSERT INTO offline_participant_links (
                    participant_id, user_id, status, method, confidence,
                    confirmed_by, confirmed_at
                ) VALUES (?, ?, 'confirmed', ?, ?, ?,
                          strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                """,
                (
                    int(participant_id), int(user_id), method,
                    None if confidence is None else float(confidence), int(admin_id),
                ),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def revoke_link(self, participant_id: int, admin_id: int) -> None:
        conn = self._db.connection
        try:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                """
                UPDATE offline_participant_links
                SET status = 'revoked',
                    revoked_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE participant_id = ? AND status = 'confirmed' AND revoked_at IS NULL
                """,
                (int(participant_id),),
            )
            await conn.execute(
                """
                UPDATE offline_participants
                SET matched_user_id = NULL, match_status = 'rejected',
                    match_method = NULL, match_confidence = NULL,
                    confirmed_by = NULL, confirmed_at = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
                WHERE participant_id = ?
                """,
                (int(participant_id),),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


class OfflineAttemptRepository:
    """`offline_attempts` va `offline_responses`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_for_exam(
        self, exam_id: int, *, include_void: bool = False
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT a.*, p.student_code, p.full_name, p.class_label,
                   p.matched_user_id, p.match_status
            FROM offline_attempts a
            JOIN offline_participants p ON p.participant_id = a.participant_id
            WHERE a.exam_id = ?
        """
        params: list[Any] = [int(exam_id)]
        if not include_void:
            sql += " AND a.status = 'valid'"
        sql += " ORDER BY a.theta DESC, a.offline_attempt_id"
        return await self._db.fetchall(sql, tuple(params))

    async def get_for_participant(
        self, exam_id: int, participant_id: int
    ) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM offline_attempts WHERE exam_id = ? AND participant_id = ? AND status = 'valid'",
            (int(exam_id), int(participant_id)),
        )

    async def list_responses(self, offline_attempt_id: int) -> list[dict[str, Any]]:
        return await self._db.fetchall(
            """
            SELECT * FROM offline_responses
            WHERE offline_attempt_id = ? ORDER BY position, display_label
            """,
            (int(offline_attempt_id),),
        )

    async def count_for_exam(self, exam_id: int) -> int:
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM offline_attempts WHERE exam_id = ? AND status = 'valid'",
                (int(exam_id),),
                default=0,
            )
        )


class OfflineDecisionRepository:
    """`exam_ranking_decisions` — kim reytingda, kim yo'q."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self, *, exam_id: int, subject_type: str, subject_id: int,
        source: str, included: int, reason: str, admin_id: int | None = None,
    ) -> None:
        conn = self._db.connection
        try:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                """
                UPDATE exam_ranking_decisions SET is_active = 0
                WHERE exam_id = ? AND subject_type = ? AND subject_id = ? AND is_active = 1
                """,
                (int(exam_id), subject_type, int(subject_id)),
            )
            await conn.execute(
                """
                INSERT INTO exam_ranking_decisions (
                    exam_id, subject_type, subject_id, source, included_in_ranking,
                    reason, decided_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(exam_id), subject_type, int(subject_id), source,
                    1 if included else 0, reason,
                    None if admin_id is None else int(admin_id),
                ),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_active(
        self, exam_id: int, subject_type: str, subject_id: int
    ) -> dict[str, Any] | None:
        return await self._db.fetchone(
            """
            SELECT * FROM exam_ranking_decisions
            WHERE exam_id = ? AND subject_type = ? AND subject_id = ? AND is_active = 1
            """,
            (int(exam_id), subject_type, int(subject_id)),
        )

    async def list_active(
        self, exam_id: int, *, source: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM exam_ranking_decisions WHERE exam_id = ? AND is_active = 1"
        params: list[Any] = [int(exam_id)]
        if source:
            sql += " AND source = ?"
            params.append(str(source))
        return await self._db.fetchall(sql, tuple(params))

    async def deactivate(self, exam_id: int, subject_type: str, subject_id: int) -> None:
        await self._db.execute(
            """
            UPDATE exam_ranking_decisions SET is_active = 0
            WHERE exam_id = ? AND subject_type = ? AND subject_id = ? AND is_active = 1
            """,
            (int(exam_id), subject_type, int(subject_id)),
        )

    async def is_excluded(self, exam_id: int, subject_type: str, subject_id: int) -> bool:
        row = await self.get_active(exam_id, subject_type, subject_id)
        return bool(row is not None and int(row.get("included_in_ranking") or 0) == 0)
