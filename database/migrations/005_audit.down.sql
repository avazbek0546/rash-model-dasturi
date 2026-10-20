-- ===========================================================================
-- 005_audit.down.sql — 005 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- OGOHLANTIRISH: audit izi o'chadi (teskari tiklab bo'lmaydi). Ishlab
--                chiqarishda avval `data/math_bot.db` nusxasini oling.
-- Faqat shu migratsiya yaratgan jadval o'chiriladi.
-- ===========================================================================

DROP TABLE IF EXISTS audit_log;
