-- 2026-10-23: the take-off register. Run once in Supabase > SQL Editor. Safe to run twice.
-- Then run the "Take-off register" action once (it fills the register and ties the outings already published).
--
-- Official take-offs come from the FFVL (open data, Licence Ouverte 2.0) and OpenStreetMap (ODbL); a take-off point
-- that none of them is close to gets a provisional take-off. Written by the server only (scripts/sync_sites.py and
-- scripts/process_pending.py, service key); everybody can read it.

create table if not exists public.takeoff_sites (
  id bigint generated always as identity primary key,
  source text not null check (source in ('ffvl', 'osm', 'provisional')),
  source_id text not null,          -- FFVL suid, OSM "node/123", or the outing a provisional take-off was made from
  name text not null,
  lat double precision not null,
  lon double precision not null,
  alt real,
  country_code text,
  wind_ok text,                     -- good wind directions (FFVL "NW;W", OSM free_flying:wind_direction)
  hike_and_fly text,                -- FFVL's hike & fly description
  ffvl_status text,                 -- FFVL: actif, ...
  merged_into bigint references public.takeoff_sites (id) on delete set null,  -- later: two take-offs found to be one
  updated_at timestamptz not null default now(),
  unique (source, source_id)
);

alter table public.takeoff_sites enable row level security;
drop policy if exists "Take-offs are public" on public.takeoff_sites;
create policy "Take-offs are public" on public.takeoff_sites for select to anon, authenticated using (true);
revoke all on public.takeoff_sites from anon, authenticated;
grant select on public.takeoff_sites to anon, authenticated;

-- the take-off an outing is tied to: auto (under 100 m), to_confirm (100-200 m), provisional (made from it),
-- manual (set by hand, never changed by the sync); and how far its take-off point is from it
alter table public.outings add column if not exists takeoff_site_id bigint references public.takeoff_sites (id) on delete set null;
alter table public.outings add column if not exists takeoff_site_status text
  check (takeoff_site_status in ('auto', 'to_confirm', 'provisional', 'manual'));
alter table public.outings add column if not exists takeoff_site_m real;
create index if not exists outings_takeoff_site_idx on public.outings (takeoff_site_id);

-- The public, verified outings for the take-off map, as one JSON array of [id, take-off lat, lon, alt, take-off
-- name, title, date, D+ on foot, km on foot, start place, pilot, highest point, pilot id, climb, take-off id,
-- tie status]. One JSON value rather than rows, so the API row limit (1,000) does not cut the map.
create or replace function public.map_outings() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(o.id, o.takeoff_lat, o.takeoff_lon, o.takeoff_alt, o.takeoff_name, o.title,
           o.outing_date, o.dplus_m, o.walk_km, o.start_place, p.display_name, o.summit_alt, o.user_id, o.climb,
           o.takeoff_site_id, o.takeoff_site_status)
         order by o.outing_date desc), '[]'::json)
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and o.verified and not o.hidden
    and o.takeoff_lat is not null and o.takeoff_lon is not null
$$;

-- The take-offs those outings are tied to: [id, name, lat, lon, alt, source, wind_ok, hike_and_fly].
create or replace function public.map_takeoff_sites() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(s.id, s.name, s.lat, s.lon, s.alt, s.source, s.wind_ok, s.hike_and_fly)), '[]'::json)
  from public.takeoff_sites s
  where s.id in (select o.takeoff_site_id from public.outings o
                 where o.status = 'published' and o.verified and not o.hidden and o.takeoff_site_id is not null)
$$;

grant execute on function public.map_outings() to anon, authenticated;
grant execute on function public.map_takeoff_sites() to anon, authenticated;
