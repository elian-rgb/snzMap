/**
 * The federal awards data, which is two different things wearing one name.
 *
 * `FederalAward` is a map feature: an award that names a venue in the spine. There are eight
 * of them. That is not a loading bug — matching federal award descriptions to venue names
 * without confirming the place of performance produced twelve hits of which ten were wrong
 * ("JOINT TASK FORCE" matched a Nevada music venue called The Joint), so the pipeline also
 * requires the award's ZIP to fall in the venue's ZCTA, and most awards correctly decline.
 *
 * `FederalProfile` is not a map feature at all. It is $5.0B of federal food-service
 * spending by operator, and it stays in a panel because it has no geography: Sodexo's
 * Marine Corps mess hall contracts are performed across dozens of posts that this spine,
 * built from stadiums and arenas, does not contain. Painting that total on the eight venues
 * that did match would be off by four orders of magnitude and look authoritative.
 */

export interface FederalAward {
  award_id: string;
  piid: string | null;
  venue_id: string;
  venue_name: string | null;
  city: string | null;
  state: string | null;
  operator: string | null;
  operator_raw: string | null;
  awarding_agency: string | null;
  awarding_sub_agency: string | null;
  fiscal_year: number | null;
  start_date: string | null;
  end_date: string | null;
  obligated_amount: number | null;
  description: string | null;
  venue_match: string;
}

export interface OperatorTotal {
  operator: string;
  awards: number;
  obligated: number;
}

export interface AgencyTotal {
  agency: string;
  awards: number;
  obligated: number;
}

export interface FederalProfile {
  awards: number;
  /** Every row read from the USAspending exports, survivors and rejects together. */
  rows_loaded: number;
  /** Rows per scope decision — `in_scope`, `remote_sites`, `foreign_performance`,
   *  `not_food_service`. Carried so the panel can state what it threw away instead of
   *  retyping the figures: "9,672 read, 393 kept" is the layer's central claim, and a
   *  hand-written version of it would keep reading true after the export moved. */
  scope_counts: Record<string, number>;
  obligated_total: number;
  by_operator: OperatorTotal[];
  by_fiscal_year: { fiscal_year: number; operators: Record<string, number> }[];
  by_agency: AgencyTotal[];
}

/**
 * Both files are fetched the same way the tenure layer is, and for the same reason: the
 * dev server answers a missing file with index.html and a 200, so the status code alone
 * cannot tell "not emitted yet" from "emitted and empty". Only the content type can.
 */
async function loadJson<T>(src: string): Promise<T | null> {
  const res = await fetch(src);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load ${src}: ${res.status}`);
  if (!(res.headers.get('content-type') ?? '').includes('json')) return null;
  return (await res.json()) as T;
}

export async function loadFederalAwards(src: string): Promise<FederalAward[]> {
  const fc = await loadJson<GeoJSON.FeatureCollection>(src);
  if (!fc) return [];
  return fc.features.map((f) => f.properties as unknown as FederalAward);
}

export async function loadFederalProfile(src: string): Promise<FederalProfile | null> {
  return loadJson<FederalProfile>(src);
}

/**
 * What the map is actually able to show: the dollars, awards and venues behind the rings.
 *
 * Computed rather than read from the profile, because the profile's `obligated_total` is a
 * different universe — every federal food-service award to these four operators, wherever
 * performed. The two numbers differ by more than four orders of magnitude ($107K against
 * $5.0B), so the one that describes the map has to be derivable on its own rather than
 * inferred by a reader subtracting.
 */
export function venueAwardTotals(awards: FederalAward[]): {
  awards: number;
  obligated: number;
  venues: number;
  names: string[];
} {
  // `names` is derived rather than written into the sidebar prose. The sentence there used
  // to name the convention centre by hand, and it survived a join change that added two more
  // venues — so the console spent a moment asserting "all at the Walter E. Washington
  // Convention Center" underneath a headline that already said three. A hand-written example
  // is a claim about the data, and this file is where the data is.
  const byVenue = new Map<string, number>();
  for (const a of awards) {
    byVenue.set(a.venue_id, (byVenue.get(a.venue_id) ?? 0) + (a.obligated_amount ?? 0));
  }
  const nameOf = new Map(awards.map((a) => [a.venue_id, a.venue_name ?? a.venue_id]));
  return {
    awards: awards.length,
    obligated: awards.reduce((sum, a) => sum + (a.obligated_amount ?? 0), 0),
    venues: byVenue.size,
    names: [...byVenue.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id]) => nameOf.get(id) as string),
  };
}

/** "A", "A and B", "A, B and C" — an English list, so the sidebar can name what it found
 *  without a hand-written sentence going stale the next time the join changes. */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** Awards at one venue, newest first — the order a reader scanning for "who has it now"
 *  wants, which is the opposite of the tenure panel's oldest-first history. */
export function awardsForVenue(
  awards: FederalAward[],
  venueId: string | null | undefined
): FederalAward[] {
  if (!venueId) return [];
  return awards
    .filter((a) => a.venue_id === venueId)
    .sort((a, b) => (b.fiscal_year ?? 0) - (a.fiscal_year ?? 0));
}

/** Compact dollars. A panel showing $4,992,628,764 next to $426,659 makes the reader count
 *  digits to compare them; $5.0B next to $427K does not. */
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${Math.round(n)}`;
}
