-- ===========================================================================
-- 006_item_difficulty_stats.sql — Vaqtinchalik item statistikasi (p -> b)
-- ===========================================================================
-- Maqsad : test (sessiya) yopilgach HAR BIR element uchun klassik statistika
--          (N, correct, wrong, blank, p, b) ni saqlash. Admin qo'lda `b`
--          kiritmaydi — bot avtomatik hisoblaydi (services/item_statistics.py).
-- Nega   : mavjud `item_statistics` jadvali (004) boshqa modelga tegishli
--          (`item_version_id` + `session_id`, item-level Rasch oqimi uchun).
--          U bilan to'qnashmaslik uchun alohida, sodda jadval yaratiladi.
--          (Eslatma: nom `item_difficulty_stats` — so'ralgan `item_statistics`
--          nomi band bo'lgani uchun; ustunlar ro'yxati so'ralganidek.)
-- Formula: p = correct / N   (N = barcha qatnashchilar; bo'shlar ham kiradi!)
--          p = clip(p, 0.01, 0.99)
--          b = ln((1 - p) / p)
-- Bog'lanishlar: item_difficulty_stats -> exam_sessions(session_id)
-- Diqqat : bu VAQTINCHALIK statistika. Kelajakda haqiqiy Rasch kalibrovkasi
--          (`calibrate(X)`) shu interfeys orqali almashtiriladi.
-- Idempotentlik: `IF NOT EXISTS` — qayta ishga tushirish xavfsiz.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS item_difficulty_stats (
    stat_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id            INTEGER NOT NULL
                       REFERENCES exam_sessions (session_id) ON DELETE CASCADE,
    item_no            TEXT    NOT NULL,               -- "1".."35", "36a".."45b"
    total_participants INTEGER NOT NULL DEFAULT 0,     -- N (bo'shlar ham kiradi)
    correct_count      INTEGER NOT NULL DEFAULT 0,     -- to'g'ri javoblar
    wrong_count        INTEGER NOT NULL DEFAULT 0,     -- noto'g'ri javoblar
    blank_count        INTEGER NOT NULL DEFAULT 0,     -- bo'sh (blank) javoblar
    percent_correct    REAL,                           -- correct / N * 100
    b_value            REAL,                           -- ln((1-p)/p), logit
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (test_id, item_no)
);

-- Test bo'yicha statistikani tez o'qish (admin hisoboti)
CREATE INDEX IF NOT EXISTS ix_item_difficulty_test
    ON item_difficulty_stats (test_id);

-- Element bo'yicha tarix (kelajakdagi drift tahlili uchun)
CREATE INDEX IF NOT EXISTS ix_item_difficulty_item
    ON item_difficulty_stats (item_no, created_at DESC);
