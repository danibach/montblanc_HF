-- « Les Esserts » above Talloires is the landing field of Perroix (Sarah, 30 October 2026): the outings analysed
-- before the engine used the pilots' name (src/mbhf/places.py, START_NAMES) get it too, in their start and title.
-- Only within about 2 km of the place: other villages have a « Les Esserts » of their own.
-- Applied once on merge by the « Migrate » action; can be run again without harm (it changes nothing the second time).

update public.outings
set start_place = 'Perroix',
    title = replace(title, 'Les Esserts', 'Perroix')
where start_place = 'Les Esserts'
  and start_lat between 45.834 and 45.870
  and start_lon between 6.186 and 6.238;
