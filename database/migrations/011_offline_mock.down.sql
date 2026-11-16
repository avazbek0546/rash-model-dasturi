-- ===========================================================================
-- 011_offline_mock.down.sql — Offline mock jadvallarini orqaga qaytarish
-- ===========================================================================
-- Diqqat: bu fayl faqat yangi jadvallarni o'chiradi. Mavjud onlayn jadvallar
-- (users, exams, user_answers, forms, attempts, responses) tegilmaydi.
-- Production'da offline ma'lumot yozilgandan keyin bu faylni ishlatmang —
-- avval bazani nusxalang.
-- ===========================================================================

DROP TABLE IF EXISTS exam_ranking_decisions;
DROP TABLE IF EXISTS offline_responses;
DROP TABLE IF EXISTS offline_attempts;
DROP TABLE IF EXISTS offline_participant_links;
DROP TABLE IF EXISTS offline_participants;
DROP TABLE IF EXISTS offline_import_issues;
DROP TABLE IF EXISTS offline_import_rows;
DROP TABLE IF EXISTS offline_import_batches;
