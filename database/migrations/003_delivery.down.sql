-- ===========================================================================
-- 003_delivery.down.sql — 003 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Tartib: bola -> ota (responses, attempts, exam_sessions).
-- OGOHLANTIRISH: bu buyruq O'QUVCHI JAVOBLARINI O'CHIRADI (faqat shu
--                migratsiya yaratgan jadvallardan). Ishlab chiqarishda avval
--                `data/math_bot.db` nusxasini oling (docs/05 rollback qoidasi).
-- Legacy `exams` / `user_answers` TEGILMAYDI.
-- ===========================================================================

DROP TABLE IF EXISTS responses;
DROP TABLE IF EXISTS attempts;
DROP TABLE IF EXISTS exam_sessions;
