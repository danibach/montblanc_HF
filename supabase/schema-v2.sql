-- Hike & Fly platform, version 2: accounts, outings, ranking.
-- Supabase > SQL Editor > New query > paste everything > Run. It can be run again without harm.
--
-- How it works:
--  * a participant signs in (e-mail link or Google): a row in "profiles" is created for them
--  * the participant uploads the track file (private storage) and adds a row in "outings" with
--    status 'pending'. The browser cannot write anything else: the results are computed by the
--    analysis job (scripts/process_pending.py, run by GitHub Actions) which fills in the row and
--    sets the status to 'published' or 'rejected'
--  * everybody can read published outings and profiles; the original files stay private

-- ---------------------------------------------------------------------------------------------
-- profiles

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now(),
  constraint profiles_name_len check (display_name is null or char_length(display_name) between 2 and 40)
);

-- one display name per person (upper or lower case does not matter)
create unique index if not exists profiles_name_unique
  on public.profiles (lower(display_name)) where display_name is not null;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id) on conflict do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- people who signed up before this script ran
insert into public.profiles (id) select id from auth.users on conflict do nothing;

alter table public.profiles enable row level security;
drop policy if exists "Profiles are public" on public.profiles;
create policy "Profiles are public" on public.profiles for select to anon, authenticated using (true);
drop policy if exists "Edit own profile" on public.profiles;
create policy "Edit own profile" on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

revoke all on public.profiles from anon, authenticated;
grant select on public.profiles to anon, authenticated;
grant update (display_name) on public.profiles to authenticated;

-- ---------------------------------------------------------------------------------------------
-- outings

create table if not exists public.outings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  status text not null default 'pending' check (status in ('pending', 'published', 'rejected')),
  reject_reason text,
  hidden boolean not null default false,
  -- false until the server job has recomputed the result from the original file
  verified boolean not null default false,

  -- the file, as announced by the browser (the job recomputes the hash)
  file_path text not null,
  file_format text not null check (file_format in ('gpx', 'fit', 'kml', 'igc', 'tcx')),
  file_size integer,
  file_sha256 text,

  -- the browser's own analysis (shown at once, "validation pending"), then rewritten by the job
  analysed_at timestamptz,
  engine_version text,
  score_version smallint,
  title text,
  outing_date date,
  started_at timestamptz,
  duration_s integer,
  country_code text,
  country_name text,
  start_lat double precision, start_lon double precision, start_alt real,
  start_place text, start_commune text,
  summit_name text, summit_osm_id bigint,
  summit_lat double precision, summit_lon double precision, summit_alt real,
  takeoff_name text,
  takeoff_lat double precision, takeoff_lon double precision, takeoff_alt real,
  landing_lat double precision, landing_lon double precision, landing_alt real,
  dplus_m integer,
  dminus_m integer,
  walk_km real,
  flight_free_km real,
  flight_path_km real,
  score integer,
  flights jsonb,
  trace jsonb,
  warnings jsonb,
  places_pending boolean not null default false
);

alter table public.outings add column if not exists verified boolean not null default false;
-- one outing in several files: every stored file in time order, [{path, format, size, sha256, name}]; null for
-- one file (file_path is then the only one). See migration-2026-10-25-file-parts.sql
alter table public.outings add column if not exists file_parts jsonb;
-- the climb on foot drawn on the take-off map, written by the server job only:
-- {line: [[lat, lon], …], dplus_m, km, duration_s}, {} when there is no climb to draw
alter table public.outings add column if not exists climb jsonb;
-- flights the participant marked by hand on the map: [[from, to], ...] in seconds after the first fix of the track.
-- The job uses them instead of the automatic detection (and skips the ground check); see migration-2026-10-25-manual-flights.sql
alter table public.outings add column if not exists manual_flights jsonb;
alter table public.outings drop constraint if exists outings_manual_flights_check;
alter table public.outings add constraint outings_manual_flights_check
  check (manual_flights is null or (jsonb_typeof(manual_flights) = 'array' and jsonb_array_length(manual_flights) between 1 and 20));

-- the take-off register (FFVL open data, OpenStreetMap, provisional take-offs), written by the server only
-- (scripts/sync_sites.py, scripts/process_pending.py); see migration-2026-10-23-takeoff-sites.sql
create table if not exists public.takeoff_sites (
  id bigint generated always as identity primary key,
  source text not null check (source in ('ffvl', 'osm', 'provisional')),
  source_id text not null,
  name text not null,
  lat double precision not null,
  lon double precision not null,
  alt real,
  country_code text,
  wind_ok text,
  hike_and_fly text,
  ffvl_status text,
  merged_into bigint references public.takeoff_sites (id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (source, source_id)
);
alter table public.takeoff_sites enable row level security;
drop policy if exists "Take-offs are public" on public.takeoff_sites;
create policy "Take-offs are public" on public.takeoff_sites for select to anon, authenticated using (true);
revoke all on public.takeoff_sites from anon, authenticated;
grant select on public.takeoff_sites to anon, authenticated;

-- the take-off an outing is tied to: auto (under 100 m), to_confirm (100-200 m), provisional, manual
alter table public.outings add column if not exists takeoff_site_id bigint references public.takeoff_sites (id) on delete set null;
alter table public.outings add column if not exists takeoff_site_status text
  check (takeoff_site_status in ('auto', 'to_confirm', 'provisional', 'manual'));
alter table public.outings add column if not exists takeoff_site_m real;
create index if not exists outings_takeoff_site_idx on public.outings (takeoff_site_id);

-- routes: the climbs to one take-off that follow the same way up (src/mbhf/routes.py), made again by the server;
-- see migration-2026-10-23-routes.sql
create table if not exists public.routes (
  id bigint generated always as identity primary key,
  takeoff_site_id bigint not null references public.takeoff_sites (id) on delete cascade,
  name text not null,
  start_place text,
  line jsonb not null,
  outing_count integer not null default 0,
  parking boolean not null default false,   -- the itinerary starts at a car park (migration-2026-10-30-route-parking.sql)
  updated_at timestamptz not null default now()
);
create index if not exists routes_site_idx on public.routes (takeoff_site_id);
alter table public.routes enable row level security;
drop policy if exists "Routes are public" on public.routes;
create policy "Routes are public" on public.routes for select to anon, authenticated using (true);
revoke all on public.routes from anon, authenticated;
grant select on public.routes to anon, authenticated;
alter table public.outings add column if not exists route_id bigint references public.routes (id) on delete set null;

-- the official FFVL take-offs and landings shown on the map (migration-2026-10-25-ffvl-terrains.sql)
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

create index if not exists outings_verified_idx on public.outings (verified) where not verified;
create index if not exists outings_list_idx on public.outings (status, outing_date desc);
create index if not exists outings_user_idx on public.outings (user_id, outing_date desc);
create index if not exists outings_country_idx on public.outings (country_code);
-- the same file cannot be published (or waiting) twice
create unique index if not exists outings_file_sha_unique
  on public.outings (file_sha256) where status in ('pending', 'published');

alter table public.outings enable row level security;

drop policy if exists "Read published outings and your own" on public.outings;
create policy "Read published outings and your own" on public.outings for select to anon, authenticated
  using ((status = 'published' and not hidden) or user_id = auth.uid());

drop policy if exists "Add your own outing" on public.outings;
-- The outing is published at once on the browser's own analysis, flagged "not verified". The checks
-- below only keep absurd values out; the job recomputes everything from the file and overwrites it.
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

drop policy if exists "Delete your own outing" on public.outings;
create policy "Delete your own outing" on public.outings for delete to authenticated
  using (user_id = auth.uid());

revoke all on public.outings from anon, authenticated;
grant select on public.outings to anon, authenticated;
grant insert (
  file_path, file_format, file_size, file_sha256, file_parts, status,
  engine_version, score_version, title, outing_date, started_at, duration_s, country_code, country_name,
  start_lat, start_lon, start_alt, start_place, start_commune,
  summit_name, summit_lat, summit_lon, summit_alt,
  takeoff_name, takeoff_lat, takeoff_lon, takeoff_alt, landing_lat, landing_lon, landing_alt,
  dplus_m, dminus_m, walk_km, flight_free_km, flight_path_km, score, flights, trace, warnings, places_pending, manual_flights
) on public.outings to authenticated;
grant delete on public.outings to authenticated;

-- at most 20 uploads per person per 24 hours; 1,000 during the first 14 days of the account, so that a new
-- participant can bring all their tracks at once
create or replace function public.limit_outings() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  cap integer;
begin
  select case when p.created_at > now() - interval '14 days' then 1000 else 20 end
    into cap from public.profiles p where p.id = new.user_id;
  if (select count(*) from public.outings
        where user_id = new.user_id and created_at > now() - interval '24 hours') >= coalesce(cap, 20) then
    raise exception 'Daily upload limit reached' using errcode = 'P0001';
  end if;
  return new;
end $$;

drop trigger if exists outings_limit on public.outings;
create trigger outings_limit before insert on public.outings
  for each row execute function public.limit_outings();

-- ---------------------------------------------------------------------------------------------
-- reports (anyone signed in can flag an outing; read them in Table Editor)

create table if not exists public.reports (
  id bigint generated always as identity primary key,
  outing_id uuid not null references public.outings (id) on delete cascade,
  reporter uuid not null default auth.uid() references public.profiles (id) on delete cascade,
  reason text not null check (char_length(reason) between 1 and 500),
  created_at timestamptz not null default now()
);
alter table public.reports enable row level security;
drop policy if exists "Report an outing" on public.reports;
create policy "Report an outing" on public.reports for insert to authenticated
  with check (reporter = auth.uid());
revoke all on public.reports from anon, authenticated;
grant insert (outing_id, reason) on public.reports to authenticated;

-- ---------------------------------------------------------------------------------------------
-- ranking and filters

create or replace function public.ranking(p_year int default null, p_country text default null, p_limit int default 200)
returns table (user_id uuid, display_name text, outings bigint, dplus bigint, dminus bigint, score bigint, walk_km numeric, flight_km numeric)
language sql stable as $$
  select o.user_id, p.display_name, count(*), coalesce(sum(o.dplus_m), 0)::bigint,
         coalesce(sum(o.dminus_m), 0)::bigint, coalesce(sum(o.score), 0)::bigint,
         coalesce(sum(o.walk_km), 0)::numeric, coalesce(sum(o.flight_free_km), 0)::numeric
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and not o.hidden
    and (p_year is null or extract(year from o.outing_date) = p_year)
    and (p_country is null or o.country_code = p_country)
  group by o.user_id, p.display_name
  order by 6 desc, 3 desc
  limit least(p_limit, 500)
$$;

create or replace function public.outing_filters() returns json
language sql stable as $$
  select json_build_object(
    'years', (select coalesce(json_agg(y order by y desc), '[]'::json) from (
        select distinct extract(year from outing_date)::int as y from public.outings
        where status = 'published' and not hidden and outing_date is not null) t),
    'countries', (select coalesce(json_agg(json_build_object('code', c, 'name', coalesce(n, c)) order by coalesce(n, c)), '[]'::json) from (
        select distinct country_code as c, country_name as n from public.outings
        where status = 'published' and not hidden and country_code is not null) t)
  )
$$;

-- the public, verified outings for the take-off map, as one JSON array of [id, take-off lat, lon, alt, take-off
-- name, title, date, D+ on foot, km on foot, start place, pilot, highest point, pilot id, climb, take-off id, tie
-- status, route id]. One JSON value rather than rows, so the API row limit (1,000) does not cut the map.
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

-- the take-offs those outings are tied to: [id, name, lat, lon, alt, source, wind_ok, hike_and_fly]
create or replace function public.map_takeoff_sites() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(s.id, s.name, s.lat, s.lon, s.alt, s.source, s.wind_ok, s.hike_and_fly)), '[]'::json)
  from public.takeoff_sites s
  where s.id in (select o.takeoff_site_id from public.outings o
                 where o.status = 'published' and o.verified and not o.hidden and o.takeoff_site_id is not null)
$$;

grant execute on function public.ranking(int, text, int) to anon, authenticated;
grant execute on function public.outing_filters() to anon, authenticated;
grant execute on function public.map_outings() to anon, authenticated;
grant execute on function public.map_takeoff_sites() to anon, authenticated;

-- the routes of the map's outings: [id, take-off id, name, line, parking]
create or replace function public.map_routes() returns json
language sql stable as $$
  select coalesce(json_agg(json_build_array(r.id, r.takeoff_site_id, r.name, r.line, r.parking)), '[]'::json)
  from public.routes r
  where r.id in (select o.route_id from public.outings o
                 where o.status = 'published' and o.verified and not o.hidden and o.route_id is not null)
$$;
grant execute on function public.map_routes() to anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- delete my account: the site first deletes the person's files, then calls this.
-- Removing the user removes the profile, and with it every outing and report.

create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = public, auth as $$
begin
  if auth.uid() is null then
    raise exception 'Not signed in';
  end if;
  delete from auth.users where id = auth.uid();
end $$;

revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;

-- ---------------------------------------------------------------------------------------------
-- private storage for the original track files (10 MB each, one folder per person)

insert into storage.buckets (id, name, public, file_size_limit)
values ('track-files', 'track-files', false, 10485760)
on conflict (id) do update set file_size_limit = excluded.file_size_limit, public = false;

drop policy if exists "Own files: upload" on storage.objects;
create policy "Own files: upload" on storage.objects for insert to authenticated
  with check (bucket_id = 'track-files' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "Own files: read" on storage.objects;
create policy "Own files: read" on storage.objects for select to authenticated
  using (bucket_id = 'track-files' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "Own files: delete" on storage.objects;
create policy "Own files: delete" on storage.objects for delete to authenticated
  using (bucket_id = 'track-files' and (storage.foldername(name))[1] = auth.uid()::text);

-- ---------------------------------------------------------------------------------------------
-- Optional, once everything works: remove the test site's table and files (the "tracks" project).
-- The files of the old bucket "trace-files" must be emptied in Storage first.
--   drop table if exists public.submission_log;
--   drop table if exists public.traces;
