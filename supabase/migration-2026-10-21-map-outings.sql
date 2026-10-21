-- 2026-10-21: the take-off map (page "Map"). Run once in Supabase > SQL Editor. Safe to run twice.
-- The public outings that the server has confirmed (verified), with only what the map and its list need, as one
-- JSON array of [id, take-off lat, lon, alt, take-off name, title, date, D+ on foot, km on foot, start place,
-- pilot, highest point]. One JSON value rather than rows, so the API row limit (1,000) does not cut the map.
-- The tracks are read separately, only for the take-off that is clicked.
create or replace function public.map_outings() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(o.id, o.takeoff_lat, o.takeoff_lon, o.takeoff_alt, o.takeoff_name, o.title,
           o.outing_date, o.dplus_m, o.walk_km, o.start_place, p.display_name, o.summit_alt)
         order by o.outing_date desc), '[]'::json)
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and o.verified and not o.hidden
    and o.takeoff_lat is not null and o.takeoff_lon is not null
$$;

grant execute on function public.map_outings() to anon, authenticated;
