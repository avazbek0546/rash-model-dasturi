-- ===========================================================================
-- 002_forms.down.sql — 002 migratsiyasini ORQAGA QAYTARISH
-- ===========================================================================
-- Tartib: bola -> ota (form_items, form_versions, forms).
-- Diqqat: FAQAT shu migratsiya yaratgan jadvallar o'chiriladi.
--         `items` / `item_versions` (001) TEGILMAYDI.
-- ===========================================================================

DROP TABLE IF EXISTS form_items;
DROP TABLE IF EXISTS form_versions;
DROP TABLE IF EXISTS forms;
