-- The Pilots page also shows each pilot's total distance on foot and in flight (km).
-- The function returns more columns than before, so it has to be dropped and created again.
-- Run once in the Supabase SQL Editor, after merging the pull request.

drop function if exists public.ranking(int, text, int);

create or replace function public.ranking(p_year int default null, p_country text default null, p_limit int default 200)
returns table (user_id uuid, display_name text, outings bigint, dplus bigint, dminus bigint, score bigint, walk_km numeric, flight_km numeric)
language sql stable as $$
  select o.user_id, p.display_name, count(*), coalesce(sum(o.dplus_m), 0)::bigint,
         coalesce(sum(o.dminus_m), 0)::bigint, coalesce(sum(o.score), 0)::bigint,
         coalesce(sum(o.walk_km), 0)::numeric, coalesce(sum(o.flight_path_km), 0)::numeric
  from public.outings o join public.profiles p on p.id = o.user_id
  where o.status = 'published' and not o.hidden
    and (p_year is null or extract(year from o.outing_date) = p_year)
    and (p_country is null or o.country_code = p_country)
  group by o.user_id, p.display_name
  order by 6 desc, 3 desc
  limit least(p_limit, 500)
$$;

grant execute on function public.ranking(int, text, int) to anon, authenticated;
