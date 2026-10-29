-- ===========================================================================
-- 010_bot_settings.sql — botning oddiy sozlamalari (kalit/qiymat)
-- ===========================================================================
-- Maqsad : bot ichidan o'zgartiriladigan, deploy talab qilmaydigan
--          sozlamalarni saqlash. Birinchi ishlatilishi — admin chat
--          (`admin_chat_id`): `/admin_chat` buyrug'i guruhni bog'laydi va
--          o'sha ID shu jadvalga yoziladi (qayta ishga tushganda ham qoladi).
-- Bog'lanishlar: mustaqil jadval (foreign key yo'q).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS bot_settings (
    key        TEXT    PRIMARY KEY,
    value      TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
               DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
