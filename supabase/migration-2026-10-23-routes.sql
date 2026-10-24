-- 2026-10-23: routes, the climbs to one take-off that follow the same way up. Run once in Supabase > SQL Editor,
-- after migration-2026-10-23-takeoff-sites.sql. Safe to run twice. Then run the "Take-off register" action once:
-- it gathers the climbs of the outings already published into routes.
--
-- Written by the server only (scripts/sync_sites.py, scripts/process_pending.py; rule in src/mbhf/routes.py); everybody
-- can read it. A take-off's routes are made again from its climbs each time: their ids may change.

create table if not exists public.routes (
  id bigint generated always as identity primary key,
  takeoff_site_id bigint not null references public.takeoff_sites (id) on delete cascade,
  name text not null,               -- « From La Clusaz », « From La Clusaz (variant 2) »
  start_place text,
  line jsonb not null,              -- [[lat, lon], …]: the most central real climb of the route
  outing_count integer not null default 0,
  updated_at timestamptz not null default now()
);
create index if not exists routes_site_idx on public.routes (takeoff_site_id);

alter table public.routes enable row level security;
drop policy if exists "Routes are public" on public.routes;
create policy "Routes are public" on public.routes for select to anon, authenticated using (true);
revoke all on public.routes from anon, authenticated;
grant select on public.routes to anon, authenticated;

alter table public.outings add column if not exists route_id bigint references public.routes (id) on delete set null;

-- the map's outings, now with their route (the last value)
create or replace function public.map_outings() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(o.id, o.takeoff_lat, o.takeoff_lon, o.takeoff_alt, o.takeoff_name, o.title,
           o.outing_date, o.dplus_m, o.walk_km, o.start_place, p.display_name, o.summit_alt, o.user_id, o.climb,
           o.takeoff_site_id, o.takeoff_site_status, o.route_id)
         order by o.outing_date desc), '[]'::json)
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and o.verified and not o.hidden
    and o.takeoff_lat is not null and o.takeoff_lon is not null
$$;

-- The routes of those outings: [id, take-off id, name, line].
create or replace function public.map_routes() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(r.id, r.takeoff_site_id, r.name, r.line)), '[]'::json)
  from public.routes r
  where r.id in (select o.route_id from public.outings o
                 where o.status = 'published' and o.verified and not o.hidden and o.route_id is not null)
$$;

grant execute on function public.map_outings() to anon, authenticated;
grant execute on function public.map_routes() to anon, authenticated;
