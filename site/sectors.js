// Flying sectors, as pilots name them (Sarah, 25 October 2026): « Lac d'Annecy » says more than « 8 take-offs »
// or a weather massif (Météo-France puts Planfait in « Aravis »). The sectors of all France and their points are made
// by scripts/make_sectors.py (site/sector-points.js): a sector is a list of communes of the FFVL file.
// A take-off belongs to the sector of the nearest point, if one is closer than MAX_KM; otherwise to none (the map then
// names the group by its take-offs).

import { SECTORS } from './sector-points.js';

const MAX_KM = 15;

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

const known = new Map(); // the sector of each point already asked: the markers are drawn again at each move
/** The name of the sector of a point, or null when no sector is close enough. */
export function sectorOf(lat, lon) {
  const k = `${lat},${lon}`;
  if (known.has(k)) return known.get(k);
  let best = null;
  let bestKm = MAX_KM;
  for (const s of SECTORS) {
    for (const [plat, plon] of s.points) {
      if (Math.abs(plat - lat) > 0.2) continue; // more than 20 km north or south: not worth the sum
      const d = km(lat, lon, plat, plon);
      if (d < bestKm) { bestKm = d; best = s.name; }
    }
  }
  known.set(k, best);
  return best;
}

/**
 * How to name a group of take-offs on the map: its sector(s), the busiest first (« Aravis », « Aravis, Lac d'Annecy »,
 * « Aravis, Lac d'Annecy +2 »); without a sector, its busiest take-off (« Le Chalvet + 2 others »).
 * ``group``: [{name, lat, lon, outings}].
 */
export function groupName(group) {
  const tally = new Map();
  for (const sp of group) {
    const s = sectorOf(sp.lat, sp.lon);
    if (s) tally.set(s, (tally.get(s) || 0) + sp.outings.length);
  }
  const names = [...tally.entries()].sort((a, b) => b[1] - a[1]).map((e) => e[0]);
  if (names.length) return names.slice(0, 2).join(', ') + (names.length > 2 ? ` +${names.length - 2}` : '');
  const top = [...group].sort((a, b) => b.outings.length - a.outings.length)[0];
  return `${top.name} + ${group.length - 1} other${group.length > 2 ? 's' : ''}`;
}
