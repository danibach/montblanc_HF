-- 2026-10-21: accept TCX files (iSmoothRun, many phone apps).
-- Run once in Supabase > SQL Editor. Safe to run twice. Existing outings are not touched.
alter table public.outings drop constraint if exists outings_file_format_check;
alter table public.outings
  add constraint outings_file_format_check check (file_format in ('gpx', 'fit', 'kml', 'igc', 'tcx'));
