/**
 * ACS neighbourhood context, keyed venue -> year.
 *
 * Two things about this layer are easy to get wrong in a UI, so they are handled here once
 * rather than at each call site.
 *
 * First, the geography is a ZCTA — a postal-delivery area — and it is not the venue. A
 * stadium's ZCTA covers the offices, housing and parking around it. Every number this module
 * returns describes that neighbourhood, never the venue, and the panel says so.
 *
 * Second, the ZCTA a venue belongs to changes mid-series: ACS 5-year vintages through 2020
 * are tabulated on 2010-Census ZCTAs and later ones on 2020-Census ZCTAs, with codes reused
 * for redrawn polygons. The pipeline resolved each venue in both and stored the year's own
 * vintage on the row, so `contextForVenue` reports which boundary set the year it returned
 * was published on rather than implying one continuous geography.
 */

/** Positional row, decoded against the file's own `series_columns`. */
export interface AcsYear {
  year: number;
  workers_total: number | null;
  median_household_income: number | null;
  transit_share: number | null;
  long_commute_share: number | null;
  /** Which ZCTA this year's numbers came from, and which boundary vintage it belongs to. */
  zcta: string | null;
  zcta_vintage: 2010 | 2020;
}

interface AcsVenue {
  zcta_match: string;
  zcta_2010: string | null;
  zcta_2020: string | null;
  years: Record<string, (number | null)[]>;
}

export interface AcsContext {
  years: number[];
  series_columns: string[];
  venues_total: number;
  venues_with_context: number;
  coverage_by_match: Record<string, number>;
  geography_note: string;
  income_note: string;
  scope_note: string;
  venues: Record<string, AcsVenue>;
}

/** The last ACS 5-year vintage published on 2010-Census ZCTAs. Mirrors
 *  `ACS_LAST_2010_VINTAGE` in pipeline/schema.py; the gate there is what enforces it. */
const LAST_2010_VINTAGE = 2020;

/**
 * Fetched with the same content-type guard as the tenure and federal layers: the dev server
 * answers a missing file with index.html and a 200, so the status code cannot distinguish
 * "not emitted yet" from "emitted and empty".
 */
export async function loadAcsContext(src: string): Promise<AcsContext | null> {
  const res = await fetch(src);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load ${src}: ${res.status}`);
  if (!(res.headers.get('content-type') ?? '').includes('json')) return null;
  return (await res.json()) as AcsContext;
}

/**
 * One venue's context in one year, or null when there is none.
 *
 * Null has three distinct causes — the venue has no ZCTA at all, the venue has a ZCTA in
 * only one vintage era, or the year is outside 2011-2024 — and the panel distinguishes them
 * using `nearestYear` and `coverageNote` rather than showing one undifferentiated blank.
 */
export function contextForVenue(
  acs: AcsContext | null,
  venueId: string | null | undefined,
  year: number
): AcsYear | null {
  if (!acs || !venueId) return null;
  const v = acs.venues[venueId];
  if (!v) return null;
  const row = v.years[String(year)];
  if (!row) return null;

  const at = (name: string) => {
    const i = acs.series_columns.indexOf(name);
    return i === -1 ? null : row[i] ?? null;
  };
  const vintage = year <= LAST_2010_VINTAGE ? 2010 : 2020;
  return {
    year,
    workers_total: at('workers_total'),
    median_household_income: at('median_household_income'),
    transit_share: at('transit_share'),
    long_commute_share: at('long_commute_share'),
    zcta: vintage === 2010 ? v.zcta_2010 : v.zcta_2020,
    zcta_vintage: vintage,
  };
}

/**
 * The year closest to `year` that this venue does have context for.
 *
 * The slider runs 1850-2026 and ACS runs 2011-2024, so most positions have nothing to show.
 * Offering the nearest year — clearly labelled as a different year — is more useful than a
 * blank panel, and is honest as long as the panel never presents it as the slider's year.
 */
export function nearestYear(
  acs: AcsContext | null,
  venueId: string | null | undefined,
  year: number
): number | null {
  if (!acs || !venueId) return null;
  const v = acs.venues[venueId];
  if (!v) return null;
  const years = Object.keys(v.years).map(Number);
  if (!years.length) return null;
  return years.reduce((best, y) =>
    Math.abs(y - year) < Math.abs(best - year) ? y : best
  );
}

/** Why a venue has no context, in words, when it has none. Null when it has some. */
export function coverageNote(
  acs: AcsContext | null,
  venueId: string | null | undefined
): string | null {
  if (!acs || !venueId) return null;
  const v = acs.venues[venueId];
  if (!v) return 'This venue is not in the ACS join — it carries no coordinate to place.';
  if (Object.keys(v.years).length) return null;
  if (v.zcta_match === 'no_zcta') {
    return (
      'This venue\u2019s coordinate falls outside every ZIP Code Tabulation Area. ZCTAs are ' +
      'built from addressed mail delivery, so water, piers and unaddressed land have none.'
    );
  }
  return 'No ACS estimates were published for this venue\u2019s ZCTA.';
}

export function percent(share: number | null): string {
  return share === null ? '\u2014' : `${Math.round(share * 100)}%`;
}

export function dollars(n: number | null): string {
  return n === null ? '\u2014' : `$${n.toLocaleString()}`;
}
