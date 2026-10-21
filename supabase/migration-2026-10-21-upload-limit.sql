-- 2026-10-21: a new account may upload up to 1,000 tracks per day during its first 14 days (20 per day afterwards).
-- Run once in Supabase > SQL Editor. Safe to run twice.
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
