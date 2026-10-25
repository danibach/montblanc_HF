// Flying sectors, as pilots name them (Sarah, 25 October 2026): « Lac d'Annecy » says more than « 8 take-offs »
// or a weather massif (Météo-France puts Planfait in « Aravis »).
// A take-off belongs to the sector of the nearest of its points, if one is closer than MAX_KM; otherwise to none
// (the map then names the group by its take-offs). To add a sector or move a border, add a point where pilots
// would say the name. Points are [lat, lon], placed on known take-offs.

const MAX_KM = 15;

export const SECTORS = [
  { name: "Lac d'Annecy", points: [[45.853, 6.223], [45.814, 6.247], [45.828, 6.287], [45.775, 6.292], [45.815, 6.187], [45.796, 6.104], [45.730, 6.196]] },
  { name: 'Aravis', points: [[45.893, 6.408], [45.890, 6.460], [45.909, 6.508], [45.924, 6.530], [45.870, 6.441], [45.826, 6.370], [45.804, 6.418], [45.959, 6.477]] },
  { name: 'Bornes', points: [[46.020, 6.346], [45.960, 6.242], [46.043, 6.419], [45.985, 6.300]] },
  { name: 'Bauges', points: [[45.689, 6.194], [45.646, 6.115], [45.600, 6.150]] },
  { name: 'Salève', points: [[46.149, 6.189], [46.100, 6.150]] },
  { name: 'Chablais', points: [[46.106, 6.455], [46.200, 6.550], [46.250, 6.650]] },
  { name: 'Giffre – Grand Massif', points: [[46.116, 6.721], [46.060, 6.680], [46.010, 6.620]] },
  { name: 'Passy – Plaine-Joux', points: [[45.945, 6.682], [45.950, 6.702], [45.920, 6.620]] },
  { name: 'Chamonix – Mont-Blanc', points: [[45.936, 6.851], [45.968, 6.876], [45.833, 6.865], [46.023, 6.851], [45.880, 6.900]] },
  { name: 'Alpes vaudoises – Chablais', points: [[46.359, 7.002], [46.321, 7.068], [46.388, 7.060], [46.319, 6.879], [46.258, 6.889], [46.351, 6.833]] },
  { name: 'Valais – Verbier', points: [[46.061, 7.355], [46.100, 7.220]] },
  { name: 'Jura', points: [[46.854, 6.612], [46.773, 6.466], [46.445, 6.176], [46.368, 6.080], [46.299, 5.983], [46.600, 6.300]] },
];

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

/** The name of the sector of a point, or null when no sector is close enough. */
export function sectorOf(lat, lon) {
  let best = null;
  let bestKm = MAX_KM;
  for (const s of SECTORS) {
    for (const [plat, plon] of s.points) {
      const d = km(lat, lon, plat, plon);
      if (d < bestKm) { bestKm = d; best = s.name; }
    }
  }
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
