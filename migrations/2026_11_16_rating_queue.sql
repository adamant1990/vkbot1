-- Безопасная миграция очереди оценок.
-- Выполнять один раз на PostgreSQL после резервной копии БД.
-- Старые trip_id/from_user_vk_id сохраняются как legacy-поля для аудита,
-- но новые записи используют booking_id/from_user_id.

BEGIN;

ALTER TABLE pending_ratings
    ADD COLUMN booking_id INTEGER,
    ADD COLUMN from_user_id INTEGER,
    ADD COLUMN sent_at TIMESTAMPTZ,
    ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN last_error TEXT;

-- Старый код записывал Booking.id в pending_ratings.trip_id.
-- Восстанавливаем правильные связи по бронированию и участникам поездки.
UPDATE pending_ratings AS pending
SET
    booking_id = booking.id,
    from_user_id = sender.id
FROM bookings AS booking
JOIN trips AS trip ON trip.id = booking.trip_id
JOIN users AS passenger ON passenger.id = booking.passenger_id
JOIN users AS driver ON driver.id = trip.driver_id,
users AS sender
WHERE sender.vk_id = pending.from_user_vk_id
  AND pending.trip_id = booking.id
  AND (
      (pending.to_user_id = passenger.id AND sender.id = driver.id)
      OR
      (pending.to_user_id = driver.id AND sender.id = passenger.id)
  );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pending_ratings
        WHERE booking_id IS NULL OR from_user_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'Migration stopped: some pending_ratings rows could not be mapped to a booking and sender. Inspect pending_ratings before retrying.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pending_ratings
        GROUP BY booking_id, from_user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Migration stopped: duplicate pending rating requests exist for the same booking and sender.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ratings
        GROUP BY booking_id, from_user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Migration stopped: duplicate ratings exist for the same booking and sender. Resolve duplicates before retrying.';
    END IF;
END $$;

ALTER TABLE pending_ratings
    ALTER COLUMN booking_id SET NOT NULL,
    ALTER COLUMN from_user_id SET NOT NULL,
    ALTER COLUMN trip_id DROP NOT NULL,
    ALTER COLUMN from_user_vk_id DROP NOT NULL;

ALTER TABLE pending_ratings
    ADD CONSTRAINT pending_ratings_booking_id_fkey
        FOREIGN KEY (booking_id) REFERENCES bookings(id),
    ADD CONSTRAINT pending_ratings_from_user_id_fkey
        FOREIGN KEY (from_user_id) REFERENCES users(id),
    ADD CONSTRAINT uq_pending_ratings_booking_from_user
        UNIQUE (booking_id, from_user_id);

ALTER TABLE ratings
    ADD CONSTRAINT uq_ratings_booking_from_user
        UNIQUE (booking_id, from_user_id);

COMMIT;
