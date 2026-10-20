-- ===========================================================================
-- 008_bot_admins.sql — bot ichidan qo'shilgan qo'shimcha adminlar
-- ===========================================================================
-- Maqsad : `/admins` paneli orqali qo'shilgan o'qituvchilarni saqlash.
-- Nega   : avval adminlar faqat `.env` dagi `ADMIN_ID`/`ADMIN_IDS` dan olinardi
--          (o'zgartirish uchun qayta deploy kerak edi). Endi botdan turib
--          qo'shish/o'chirish mumkin, o'zgarish shu jadvalda saqlanadi va bot
--          ishga tushganda xotiraga yuklanadi (`config.set_db_admins`).
-- Diqqat : `.env` dagi adminlar "egasi" hisoblanadi va bu jadval orqali
--          O'CHIRILMAYDI (lock-out himoyasi).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS bot_admins (
    user_id    INTEGER PRIMARY KEY,                 -- Telegram user id
    full_name  TEXT,                                -- qo'shilgan paytdagi ism
    username   TEXT,                                -- @username (bo'lsa)
    added_by   INTEGER,                             -- kim qo'shgan (Telegram id)
    added_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- Ro'yxatni qo'shilish tartibida ko'rsatish uchun.
CREATE INDEX IF NOT EXISTS ix_bot_admins_added_at
    ON bot_admins (added_at);
