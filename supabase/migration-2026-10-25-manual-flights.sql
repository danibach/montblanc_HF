-- 2026-10-25: flights marked by hand on the map (Upload > "Mark the flight by hand").
-- The browser sends the marked stretches with the outing; the server job then analyses the file with them instead
-- of the automatic detection, and skips the ground check on them.
-- Run once in Supabase > SQL Editor, BEFORE the site that sends this column is put online. Safe to run twice.
-- Existing outings are not touched.
alter table public.outings add column if not exists manual_flights jsonb;
alter table public.outings drop constraint if exists outings_manual_flights_check;
alter table public.outings add constraint outings_manual_flights_check
  check (manual_flights is null or (jsonb_typeof(manual_flights) = 'array' and jsonb_array_length(manual_flights) between 1 and 20));
grant insert (manual_flights) on public.outings to authenticated;
