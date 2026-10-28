-- ===========================================================================
-- 009_user_profiles.down.sql — 009 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Diqqat: `users` jadvaliga tegilmagan, shu sababli rollback faqat shu
-- migratsiya yaratgan jadvalni o'chiradi.

DROP INDEX IF EXISTS ix_user_profiles_updated_at;
DROP TABLE IF EXISTS user_profiles;
