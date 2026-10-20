-- ===========================================================================
-- 007_result_notify.down.sql — 007 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Faqat shu migratsiya qo'shgan ustun va indeks o'chadi.
-- ===========================================================================

DROP INDEX IF EXISTS ix_user_answers_notified;
ALTER TABLE user_answers DROP COLUMN notified_at;
