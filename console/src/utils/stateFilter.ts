/**
 * The state filter, and why there is no city filter next to it.
 *
 * `state` is trustworthy: 5,799 of 6,884 venues carry one (84.2%), every value is a valid
 * two-letter code, and there are 51 of them (50 states plus DC).
 *
 * `city` is not, and the measurement is worth keeping because the field looks fine until you
 * check it against geometry. 2,469 venues (35.9%) have their own state's full name sitting in
 * the city field — Cajundome's city is "Louisiana", Charlotte Motor Speedway's is "North
 * Carolina". Where the state's name is also a real city the damage is invisible to a string
 * check: 177 venues are labelled city "New York", and 122 of them (69%) are more than 60 km
 * from Manhattan, including six around Niagara Falls at ~495 km. A city dropdown built on
 * this would file Niagara Falls Country Club under New York City and look authoritative
 * doing it. Until the spine has a real locality — reverse-geocoded, not scraped from a
 * Wikidata label — there is nothing here to filter on.
 */

import type { VenueProperties } from './spineTransform';

export const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
  CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia',
  FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana',
  IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland',
  MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri',
  MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey',
  NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio',
  OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island',
  SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah',
  VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin',
  WY: 'Wyoming',
};

export interface StateCount {
  code: string;
  name: string;
  /** Venues in this state in the current year, after the type filter. */
  count: number;
}

/**
 * States present in the spine with their counts, alphabetical by name.
 *
 * Counted over the venues the other filters already allow, so the number beside "Texas" is
 * the number of dots picking Texas would actually leave on screen. Counting the whole spine
 * instead would promise 482 and deliver 431 once the year filter applied.
 */
export function stateCounts(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null,
  visibleVenueIds: Set<string>
): StateCount[] {
  if (!spine) return [];
  const counts = new Map<string, number>();
  for (const f of spine.features) {
    const { state, venue_id } = f.properties;
    if (!state || !visibleVenueIds.has(venue_id)) continue;
    counts.set(state, (counts.get(state) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, name: STATE_NAMES[code] ?? code, count }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Bounding box of the venues in a state, for fitting the camera.
 *
 * Derived from the dots rather than from a state outline, because the point of the fit is to
 * frame what the filter left on screen. A state whose venues all sit in one corner should
 * frame that corner, not the whole state.
 */
export function boundsForState(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null,
  state: string | null,
  visibleVenueIds: Set<string>
): [[number, number], [number, number]] | null {
  if (!spine || !state) return null;
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
  let n = 0;
  for (const f of spine.features) {
    if (f.properties.state !== state || !visibleVenueIds.has(f.properties.venue_id)) continue;
    const [lng, lat] = f.geometry.coordinates;
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
    minLng = Math.min(minLng, lng); maxLng = Math.max(maxLng, lng);
    minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
    n++;
  }
  if (n === 0) return null;
  // A state with one venue has a zero-area box, which maplibre fits by zooming to maximum.
  // Padding it to roughly a city's width keeps a single dot at a readable scale.
  if (minLng === maxLng && minLat === maxLat) {
    return [
      [minLng - 0.15, minLat - 0.15],
      [maxLng + 0.15, maxLat + 0.15],
    ];
  }
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

/** Venues with no state at all — named rather than silently excluded when a state is picked. */
export function venuesWithoutState(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null
): number {
  if (!spine) return 0;
  return spine.features.filter((f) => !f.properties.state).length;
}
