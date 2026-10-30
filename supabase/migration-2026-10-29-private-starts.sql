-- What visitors see of an outing (Sarah, 29 October 2026; src/mbhf/privacy.py).
-- A trace often starts at the pilot's door and may end there. The server writes next to the trace its public part
-- (trace_public: without the start near home, a drive before the climb, and the way back after landing) and the
-- public part of the map's climb (climb_public). Visitors are sent only those: the whole trace, the climb and the
-- start (position, altitude, place) are kept for the pilot, who reads them with my_outing_private().
-- Applied once on merge by the « Migrate » action; can be run again without harm.

alter table public.outings add column if not exists trace_public jsonb;
alter table public.outings add column if not exists climb_public jsonb;

-- every column but the private ones (trace, climb, start_lat, start_lon, start_alt, start_place)
revoke select on public.outings from anon, authenticated;
grant select (
  id, user_id, created_at, analysed_at, status, verified, hidden, reject_reason,
  file_path, file_format, file_size, file_sha256, file_parts,
  engine_version, score_version, title, outing_date, started_at, duration_s, country_code, country_name,
  start_commune,
  summit_name, summit_lat, summit_lon, summit_alt, summit_osm_id,
  takeoff_name, takeoff_lat, takeoff_lon, takeoff_alt, takeoff_site_id, takeoff_site_m, takeoff_site_status,
  landing_lat, landing_lon, landing_alt,
  dplus_m, dminus_m, walk_km, flight_free_km, flight_path_km, score, flights, warnings, places_pending,
  manual_flights, route_id, trace_public, climb_public
) on public.outings to anon, authenticated;

-- the pilot's own whole trace and start
create or replace function public.my_outing_private(p_id uuid) returns json
language sql stable security definer set search_path = public as $$
  select json_build_object('trace', o.trace, 'start_lat', o.start_lat, 'start_lon', o.start_lon,
                           'start_alt', o.start_alt, 'start_place', o.start_place)
  from public.outings o
  where o.id = p_id and o.user_id = auth.uid()
$$;
revoke all on function public.my_outing_private(uuid) from public, anon;
grant execute on function public.my_outing_private(uuid) to authenticated;

-- the take-off map: the public part of each climb, and the commune of the start rather than the place
create or replace function public.map_outings() returns json
language sql stable security definer set search_path = public as $$
  select coalesce(json_agg(json_build_array(o.id, o.takeoff_lat, o.takeoff_lon, o.takeoff_alt, o.takeoff_name, o.title,
           o.outing_date, o.dplus_m, o.walk_km, coalesce(o.start_commune, o.start_place), p.display_name, o.summit_alt,
           o.user_id, coalesce(o.climb_public, '{}'::jsonb), o.takeoff_site_id, o.takeoff_site_status, o.route_id)
         order by o.outing_date desc), '[]'::json)
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and o.verified and not o.hidden
    and o.takeoff_lat is not null and o.takeoff_lon is not null
$$;
