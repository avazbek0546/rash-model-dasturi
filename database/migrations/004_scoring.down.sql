-- ===========================================================================
-- 004_scoring.down.sql — 004 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Tartib: bola -> ota:
--   1) result_versions        (scoring_snapshots ga tayanadi)
--   2) scoring_snapshot_items (scoring_snapshots ga tayanadi)
--   3) scoring_snapshots
--   4) item_statistics
--   5) item_parameters
-- OGOHLANTIRISH: `b` tarixi va baholash snapshotlari o'chadi. Ishlab chiqarishda
--                avval `data/math_bot.db` nusxasini oling (docs/05).
-- Legacy `exams` / `user_answers` TEGILMAYDI.
-- ===========================================================================

DROP TABLE IF EXISTS result_versions;
DROP TABLE IF EXISTS scoring_snapshot_items;
DROP TABLE IF EXISTS scoring_snapshots;
DROP TABLE IF EXISTS item_statistics;
DROP TABLE IF EXISTS item_parameters;
