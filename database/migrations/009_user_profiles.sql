-- ===========================================================================
-- 009_user_profiles.sql — botda ism/familiyani majburiy ro'yxatdan o'tkazish
-- ===========================================================================
-- Maqsad : `/start` bosganda o'quvchidan ism va familiyani alohida so'rab,
--          "ro'yxatdan o'tgan" holatini saqlash.
-- Nega   : `users.full_name` Telegram'dan avtomatik to'ldiriladi va qayta
--          ishga tushganda ustidan yozilishi mumkin edi. Endi o'quvchi
--          kiritgan ism/familiya shu jadvalda saqlanadi va uning mavjudligi
--          ro'yxatdan o'tganlik belgisi bo'ladi.
-- Diqqat : legacy `users` jadvali o'zgarmaydi; `full_name` hisobotlar uchun
--          saqlanadi va ro'yxatdan o'tishda sinxronlanadi.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    INTEGER PRIMARY KEY
               REFERENCES users (user_id) ON DELETE CASCADE,
    first_name TEXT    NOT NULL,
    last_name  TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- Profilni oxirgi o'zgartirilganlar bo'yicha tez topish (admin/audit uchun).
CREATE INDEX IF NOT EXISTS ix_user_profiles_updated_at
    ON user_profiles (updated_at);
