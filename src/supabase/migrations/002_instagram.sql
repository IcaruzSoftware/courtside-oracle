-- Migration 002 — instagram_posts table + public `instagram` Storage bucket
-- Apply once in the Supabase SQL editor (idempotent; safe to re-run).

-- ---------------------------------------------------------------------------
-- 1. instagram_posts
-- One row per posted (date, kind), written by src/scripts/post_instagram.py. The
-- row is inserted as a claim (media_id NULL) BEFORE publishing; the primary key
-- makes a concurrent run's insert fail, so a post type is never posted twice.
-- RLS enabled with NO policies: service role only (not readable by the website).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS instagram_posts (
    post_date   DATE NOT NULL,                  -- ET post date (the record post covers the day before)
    kind        TEXT NOT NULL CHECK (kind IN ('predictions', 'record')),
    media_id    TEXT,                           -- Instagram media id, NULL while claimed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (post_date, kind)
);

ALTER TABLE instagram_posts ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 2. Storage bucket `instagram` (public): the slide JPEGs at <date>/<kind>/<i>.jpg.
-- The Instagram Graph API fetches the images by public URL.
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public) VALUES ('instagram', 'instagram', true)
ON CONFLICT (id) DO NOTHING;
