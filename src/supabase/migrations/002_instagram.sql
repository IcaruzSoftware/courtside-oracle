-- Migration 002 — instagram_posts table + public `instagram` Storage bucket
-- Apply once in the Supabase SQL editor (idempotent; safe to re-run).

-- ---------------------------------------------------------------------------
-- 1. instagram_posts
-- One row per posted date, written by src/scripts/post_instagram.py. The row is
-- inserted as a claim (media_id NULL) BEFORE publishing; the primary key makes a
-- concurrent run's insert fail, so a date is never posted twice.
-- RLS enabled with NO policies: service role only (not readable by the website).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS instagram_posts (
    post_date   DATE PRIMARY KEY,               -- ET game date
    media_id    TEXT,                           -- Instagram media id, NULL while claimed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE instagram_posts ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 2. Storage bucket `instagram` (public): the slide JPEGs at <date>/<i>.jpg.
-- The Instagram Graph API fetches the images by public URL.
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public) VALUES ('instagram', 'instagram', true)
ON CONFLICT (id) DO NOTHING;
