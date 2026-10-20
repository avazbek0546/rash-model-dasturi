-- ===========================================================================
-- 001_item_bank.down.sql — 001 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Tartib: avval BOLA jadval (item_versions), keyin OTA (items) — chunki
--         ulanishda `PRAGMA foreign_keys = ON` yoqilgan.
-- Diqqat: bu buyruq FAQAT shu migratsiya yaratgan jadvallarni o'chiradi.
--         Legacy jadvallar (users, exams, user_answers, ...) TEGILMAYDI.
-- ===========================================================================

DROP TABLE IF EXISTS item_versions;
DROP TABLE IF EXISTS items;
