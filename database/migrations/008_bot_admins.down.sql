-- ===========================================================================
-- 008_bot_admins.down.sql — 008 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Faqat shu migratsiya yaratgan jadval va indeks o'chadi.
-- ===========================================================================

DROP INDEX IF EXISTS ix_bot_admins_added_at;
DROP TABLE IF EXISTS bot_admins;
