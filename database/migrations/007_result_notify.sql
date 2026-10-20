-- ===========================================================================
-- 007_result_notify.sql — natija bildirishnomasi (result_time da yuborish)
-- ===========================================================================
-- Maqsad : har bir javob uchun natija xabari yuborilganini qayd etish.
-- Nega   : natija faqat `result_time` kelgach ALOHIDA fon vazifasi orqali
--          yuboriladi. `notified_at` idempotentlikni ta'minlaydi — xabar
--          ikki marta ketmaydi, bot bloklangan/o'chirilgan holat ham esda
--          qoladi.
-- Diqqat : mavjud `user_answers` jadvaliga qo'shiladi, eski yozuvlarda NULL
--          bo'ladi (ya'ni hali bildirishnoma yuborilmagan).
-- ===========================================================================

ALTER TABLE user_answers ADD COLUMN notified_at TEXT;

-- MUHIM: migratsiyadan OLDIN mavjud (va 1 kundan eski) natijalar uchun
-- `notified_at` ni belgilaymiz. Aks holda yangi notifier ishga tushganda barcha
-- eski imtihonlar bo'yicha o'quvchilarga birdaniga xabar yuborib yuboradi
-- (spam). Kelajakdagi va yaqin 1 kun ichida e'lon qilingan natijalar NULL
-- qoladi — ular `result_time` da odatdagidek yuboriladi.
UPDATE user_answers
   SET notified_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
 WHERE notified_at IS NULL
   AND exam_id IN (
       SELECT exam_id FROM exams
        WHERE result_time <= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', '-1 day')
   );

-- Navbatdagi (hali yuborilmagan) natijalarni tez topish uchun.
CREATE INDEX IF NOT EXISTS ix_user_answers_notified
    ON user_answers (notified_at);
