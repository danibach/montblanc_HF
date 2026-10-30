-- 2026-10-30: whether an itinerary starts at a car park (Sarah). The server starts an itinerary at a parking of
-- OpenStreetMap within 100 m of its start (src/mbhf/routes.py, PARKING_M) and now says so; the map draws its P from
-- that, instead of asking OpenStreetMap from the visitor's browser (Overpass, often busy or blocked by a network).
-- Applied once on merge by the « Migrate » action; can be run again without harm. The « Take-off register » action
-- then fills it in as it makes the itineraries again.

alter table public.routes add column if not exists parking boolean not null default false;

-- The routes of the map's outings: [id, take-off id, name, line, parking].
create or replace function public.map_routes() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(r.id, r.takeoff_site_id, r.name, r.line, r.parking)), '[]'::json)
  from public.routes r
  where r.id in (select o.route_id from public.outings o
                 where o.status = 'published' and o.verified and not o.hidden and o.route_id is not null)
$$;

grant execute on function public.map_routes() to anon, authenticated;
