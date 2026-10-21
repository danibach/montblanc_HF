-- 2026-10-21: the take-off heat map (page "Map"). Run once in Supabase > SQL Editor. Safe to run twice.
-- Take-offs of the public outings that the server has confirmed (verified), as one JSON array of
-- [lat, lon, outings]. Coordinates are rounded to 4 decimals (about 10 m): the same spot comes once, with
-- its number of outings. One JSON value rather than rows, so the API row limit (1,000) does not cut the map.
create or replace function public.takeoff_heat() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(lat, lon, n)), '[]'::json) from (
    select round(takeoff_lat::numeric, 4)::double precision as lat,
           round(takeoff_lon::numeric, 4)::double precision as lon,
           count(*) as n
    from public.outings
    where status = 'published' and verified and not hidden
      and takeoff_lat is not null and takeoff_lon is not null
    group by 1, 2) t
$$;

grant execute on function public.takeoff_heat() to anon, authenticated;
