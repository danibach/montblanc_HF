-- 2026-10-25: the official FFVL take-offs and landings on the map (▲ take-off, ▼ landing), with their card (winds,
-- status, walk from the car park, warnings, restrictions…). Filled by the "Take-off register" action
-- (scripts/sync_sites.py) from the FFVL open-data file (Licence Ouverte 2.0); sites for speed riding, kites or hang
-- gliders only are left out. Only for the map: outings are tied to take-offs through takeoff_sites, never to a landing.
-- Run once in Supabase > SQL Editor, then the "Take-off register" action once. Safe to run twice.
create table if not exists public.ffvl_terrains (
  suid integer primary key,          -- the FFVL's own id
  name text not null,
  lat double precision not null,
  lon double precision not null,
  alt real,
  kind text not null check (kind in ('T', 'L', 'TL')),   -- take-off, landing, both
  status text,                       -- actif, actif_autorisation_systematique_requise, interdit_sauf_autorisation, interdit
  winds text,                        -- good winds: « N;NO;O »
  info jsonb not null default '{}',  -- the card: walk_min, access, ideal, warnings, restrictions, notes, gear…
  updated_at timestamptz not null default now()
);
alter table public.ffvl_terrains enable row level security;
drop policy if exists "FFVL sites are public" on public.ffvl_terrains;
create policy "FFVL sites are public" on public.ffvl_terrains for select to anon, authenticated using (true);
revoke all on public.ffvl_terrains from anon, authenticated;
grant select on public.ffvl_terrains to anon, authenticated;

-- the light list for the map, as one JSON array of [suid, name, lat, lon, alt, kind, status, winds]; the card is read
-- on a click (select info where suid = …)
create or replace function public.map_ffvl() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(f.suid, f.name, f.lat, f.lon, f.alt, f.kind, f.status, f.winds)), '[]'::json)
  from public.ffvl_terrains f
$$;
grant execute on function public.map_ffvl() to anon, authenticated;
