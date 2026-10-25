-- 2026-10-25: one outing in several files (a bike ride to the start, the climb and flight, the ride home).
-- file_parts lists every stored file of such an outing, in time order: [{path, format, size, sha256, name}];
-- null for an outing in one file. file_path is the first part, file_sha256 the combined fingerprint
-- (src/mbhf/multi.py). The server job joins the original files again (scripts/process_pending.py).
-- Run once in Supabase > SQL Editor. Safe to run twice. Existing outings are not touched.
alter table public.outings add column if not exists file_parts jsonb;

drop policy if exists "Add your own outing" on public.outings;
create policy "Add your own outing" on public.outings for insert to authenticated
  with check (
    user_id = auth.uid() and status = 'published' and not verified and not hidden
    and file_path like auth.uid()::text || '/%'
    and dplus_m between 200 and 30000 and dminus_m between 0 and 15000
    and score = dplus_m + dminus_m
    and (trace is null or pg_column_size(trace) < 600000)
    and (file_parts is null or (
      jsonb_typeof(file_parts) = 'array'
      and jsonb_array_length(file_parts) between 2 and 10
      and not exists (
        select 1 from jsonb_array_elements(file_parts) p
        where not (p->>'path' like auth.uid()::text || '/%')
          or p->>'format' not in ('gpx', 'fit', 'kml', 'igc', 'tcx'))
    ))
  );

grant insert (file_parts) on public.outings to authenticated;
