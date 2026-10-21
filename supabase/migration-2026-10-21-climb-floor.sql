-- 2026-10-21: the database now refuses outings with less than 200 m of climb on foot (was 100 m),
-- the same floor as the engine (an outing needs at least 200 m on foot to count).
-- Run once in Supabase > SQL Editor. Safe to run twice. Existing outings are not touched.
drop policy if exists "Add your own outing" on public.outings;
create policy "Add your own outing" on public.outings for insert to authenticated
  with check (
    user_id = auth.uid() and status = 'published' and not verified and not hidden
    and file_path like auth.uid()::text || '/%'
    and dplus_m between 200 and 30000 and dminus_m between 0 and 15000
    and score = dplus_m + dminus_m
    and (trace is null or pg_column_size(trace) < 600000)
  );
