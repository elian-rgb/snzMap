/**
 * Filter the spine by the ACS neighbourhood around each venue.
 *
 * This is the only filter in the console backed by dense data: 6,831 of 6,884 venues carry a
 * ZCTA, so a commute or income band actually narrows a national map into something readable.
 *
 * Two rules, both of which exist because the alternative silently lies:
 *
 * **A venue with no context is never quietly dropped.** ACS coverage is per venue *and* per
 * year — a venue can have a ZCTA but no row for 1994, since the series only runs 2011-2024.
 * `applyBands` returns those ids in `unknown` rather than folding them into "did not match",
 * so the caller can say "1,412 venues have no ACS data for this year" instead of showing a
 * thinned map that looks like a finding.
 *
 * **The bands are thresholds, not quantiles.** A quintile split would re-cut itself every time
 * the year moved, so a venue could change band without its neighbourhood changing at all. The
 * cut points below are fixed and stated in the UI, which means a band means the same thing in
 * 2011 as in 2024 — the whole point of a time slider.
 */

import { contextForVenue, type AcsContext } from './acsTransform';
import type { VenueProperties } from './spineTransform';

export type BandKey = 'transit' | 'long_commute' | 'income';

export interface Band {
  key: BandKey;
  label: string;
  /** What the reader is choosing, in their words, not the column name. */
  question: string;
  /** Fixed cut points, ascending. Stated in the UI so the band is never a black box. */
  cuts: number[];
  /** One label per bucket; length is cuts.length + 1. */
  bucketLabels: string[];
  unit: 'percent' | 'dollars';
}

export const BANDS: Band[] = [
  {
    key: 'transit',
    label: 'Commute by transit',
    question: 'How many people around this venue get to work by transit?',
    cuts: [0.02, 0.1, 0.3],
    bucketLabels: ['Under 2%', '2–10%', '10–30%', 'Over 30%'],
    unit: 'percent',
  },
  {
    key: 'long_commute',
    label: 'Long commutes (45 min+)',
    question: 'How many people around this venue travel 45 minutes or more to work?',
    cuts: [0.1, 0.2, 0.35],
    bucketLabels: ['Under 10%', '10–20%', '20–35%', 'Over 35%'],
    unit: 'percent',
  },
  {
    key: 'income',
    label: 'Median household income',
    question: 'What does the neighbourhood around this venue earn?',
    cuts: [40000, 70000, 110000],
    bucketLabels: ['Under $40k', '$40k–$70k', '$70k–$110k', 'Over $110k'],
    unit: 'dollars',
  },
];

export const BAND_BY_KEY: Record<BandKey, Band> = Object.fromEntries(
  BANDS.map((b) => [b.key, b])
) as Record<BandKey, Band>;

function valueFor(
  acs: AcsContext | null,
  venueId: string,
  year: number,
  key: BandKey
): number | null {
  const ctx = contextForVenue(acs, venueId, year);
  if (!ctx) return null;
  if (key === 'transit') return ctx.transit_share;
  if (key === 'long_commute') return ctx.long_commute_share;
  return ctx.median_household_income;
}

/** Which bucket a value falls in, or -1 when there is no value. */
export function bucketOf(value: number | null, band: Band): number {
  if (value === null || !Number.isFinite(value)) return -1;
  let i = 0;
  while (i < band.cuts.length && value >= band.cuts[i]) i += 1;
  return i;
}

export interface BandResult {
  /** Venue ids passing the chosen buckets. */
  matched: Set<string>;
  /** Venue ids with no ACS value for this year — reported, never silently excluded. */
  unknown: Set<string>;
  /** Count per bucket, for the checkbox labels. */
  counts: number[];
}

/**
 * One color per band, so the measure can be read off the map instead of only off the counts.
 *
 * Yellow → green → teal → navy, the ColorBrewer YlGnBu family darkened until every step
 * clears WCAG 1.4.11's 3:1 on *both* positron surfaces. A coastal stadium sits on the land /
 * water boundary, so passing on land alone is not passing:
 *
 *   #a16207  yellow   land 4.71:1   water 3.48:1
 *   #166534  green    land 6.82:1   water 5.05:1
 *   #164e63  teal     land 8.72:1   water 6.45:1
 *   #172554  navy     land 14.06:1  water 10.40:1
 *
 * The ramp is **monotonic in luminance**, not just in hue. Hue alone would collapse for a
 * deuteranope and vanish entirely in a grayscale print, and this is a thing Kiki hands to
 * someone — so a reader who cannot separate the hues still sees light-to-dark in the right
 * order. That ordering is the whole reason a sequential family was used rather than four
 * distinct colors: bucket 3 is *more of the measure* than bucket 0, and the map should say so.
 *
 * It is deliberately not green-to-red. A neighbourhood where 40% of people take transit is
 * not worse than one where 2% do, and a red dot would assert that it is.
 *
 * Venues with no ACS value keep NO_DATA_COLOR — a lighter blue-grey than any of these. A gap
 * should not be the loudest mark on the map.
 */
export const BAND_COLORS = ['#a16207', '#166534', '#164e63', '#172554'];

/**
 * Venue id → band color, for the venues that have a value.
 *
 * Ids with no ACS value are simply absent from the map rather than mapped to a grey, so the
 * caller can fall through to whatever it already uses for "nothing on record" instead of this
 * module having an opinion about it.
 */
export function bandColorsFor(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null,
  acs: AcsContext | null,
  candidateIds: Set<string>,
  band: Band,
  year: number
): Map<string, string> {
  const out = new Map<string, string>();
  if (!spine) return out;
  for (const f of spine.features) {
    const id = f.properties.venue_id;
    if (!candidateIds.has(id)) continue;
    const b = bucketOf(valueFor(acs, id, year, band.key), band);
    if (b === -1) continue;
    out.set(id, BAND_COLORS[b] ?? BAND_COLORS[BAND_COLORS.length - 1]);
  }
  return out;
}

export function applyBands(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null,
  acs: AcsContext | null,
  candidateIds: Set<string>,
  band: Band,
  chosen: number[],
  year: number
): BandResult {
  const matched = new Set<string>();
  const unknown = new Set<string>();
  const counts = new Array(band.cuts.length + 1).fill(0);
  if (!spine) return { matched, unknown, counts };

  for (const f of spine.features) {
    const id = f.properties.venue_id;
    if (!candidateIds.has(id)) continue;
    const b = bucketOf(valueFor(acs, id, year, band.key), band);
    if (b === -1) {
      unknown.add(id);
      continue;
    }
    counts[b] += 1;
    // An empty selection is "no band filter", not "exclude everything" — a filter that blanks
    // the map the moment it is opened reads as a bug.
    if (chosen.length === 0 || chosen.includes(b)) matched.add(id);
  }
  return { matched, unknown, counts };
}
