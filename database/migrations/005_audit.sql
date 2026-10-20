-- ===========================================================================
-- 005_audit.sql — Audit izi (docs/11 §5.5: audit_log)
-- ===========================================================================
-- Maqsad : "kim, qachon, nimani o'zgartirdi" ni majburiy qayd etish.
-- Nega   : kalit tuzatilishi, `b` yangilanishi, o'quvchi chiqarilishi va
--          migratsiyalarning o'zi — audit talabi (docs/11 §7).
-- Diqqat : autosave (javob saqlash) BU JADVALGA YOZILMAYDI — u foydalanuvchi
--          harakati, audit emas (docs/11 invariant I12). Audit faqat muhim
--          amallar uchun: kalit/`b` o'zgarishi, yakunlash, soft delete, regrade.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,                             -- Telegram ID (bo'lsa)
    action        TEXT    NOT NULL,                    -- 'form.create', 'item_parameter.update', ...
    entity_type   TEXT    NOT NULL,                    -- 'form', 'item_version', 'attempt', 'b', ...
    entity_id     TEXT,                                -- qaysi obyekt (ID satr ko'rinishida)
    before_json   TEXT,                                -- o'zgarishdan oldingi holat (JSON)
    after_json    TEXT,                                -- o'zgarishdan keyingi holat (JSON)
    source        TEXT    NOT NULL DEFAULT 'system'
                  CHECK (source IN ('bot', 'webapp', 'admin_api', 'system', 'migration')),
    note          TEXT,                                -- izoh (sabab)
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- Obyekt bo'yicha tarix ("bu itemga nima bo'lgan?")
CREATE INDEX IF NOT EXISTS ix_audit_entity
    ON audit_log (entity_type, entity_id, created_at DESC);

-- Foydalanuvchi bo'yicha tarix ("bu admin nima qilgan?")
CREATE INDEX IF NOT EXISTS ix_audit_actor
    ON audit_log (actor_user_id, created_at DESC);

-- Umumiy xronologiya (so'nggi amallar)
CREATE INDEX IF NOT EXISTS ix_audit_created
    ON audit_log (created_at DESC);
