/**
 * Turns tenure records into the one thing the map needs: what color is each venue in year T.
 *
 * The tenure file is one row per *run* (operator × venue × span), but the map is one dot per
 * *venue*. So this module does the collapse: for a given year, find the spans covering it and
 * hand back a venue_id -> color map. That keeps the spine as a single circle layer — a second
 * GL source at identical coordinates would mean duplicate click targets and a capacity join
 * done only to keep two radii from disagreeing.
 *
 * The year window is `start_year .. render_end_year`, and `render_end_year` is doing the load
 * bearing work. The pipeline sets it three different ways (reported end / as-of for an ongoing
 * run / `known_through` for an unknown one), so an operator last seen in 1998 stops being
 * painted in 1998 instead of running silently to the present.
 */

export interface TenureProperties {
  tenure_id: string;
  venue_id: string | null;
  venue_name: string | null;
  venue_type: string | null;
  city: string | null;
  state: string | null;
  operator: string | null;
  operator_normalized: string | null;
  start_date: string | null;
  end_date: string | null;
  end_status: 'ended' | 'ongoing' | 'unknown' | null;
  exit_mode: string | null;
  start_year: number | null;
  render_end_year: number | null;
  render_end_basis: string;
  start_is_known: boolean;
  end_inferred: boolean;
  needs_review: boolean;
  event_count: number;
  source: string | null;
}

/**
 * Dot colors, every one measured against the light basemap rather than picked from a scale.
 *
 * CARTO positron draws land at roughly #fafaf8 and water at roughly #d4dadc, and a dot has
 * to clear WCAG 1.4.11's 3:1 for non-text graphics on *both* — a coastal stadium sits on
 * the boundary between them, so passing on land alone is not passing. Every value below was
 * computed against #fafaf8; NO_DATA_COLOR, the one that is drawn most, was also checked
 * against water.
 *
 * The previous palette was built for a dark navy basemap and every color in it was a bright
 * tint chosen to glow against #131a26. Carried onto white unchanged they would have measured
 * around 1.3–1.8:1 — dots you can see only because you know where to look.
 */

/**
 * In the spine, no operator on record — a documented gap, not an empty venue.
 *
 * This one matters more than the rest and gets checked hardest: tenure has zero runs today,
 * so *every* dot on the map is this color. If it is weak the whole map reads as empty rather
 * than as fully unattributed, which is precisely the false impression this project exists to
 * avoid. 4.55:1 on land, 3.37:1 on water, and far lighter than SELF_OP_COLOR so a gap never
 * starts looking like a self-operated venue.
 */
export const NO_DATA_COLOR = '#64748b';
/** Two operators hold one venue in the same year. The pipeline flags these rather than
 *  picking a winner, and so does the map. 6.01:1. */
export const CONTESTED_COLOR = '#be123c';
/** Not a vendor. Worth its own color so "who runs concessions" can be read as
 *  vendor-vs-institution without checking the legend. 14.00:1 — the darkest dot, because
 *  on a light map "definitely known" should be the heaviest mark. */
export const SELF_OP_COLOR = '#1e293b';
export const SELF_OP = 'Self-operated';
/** Everyone past the palette. Naming twenty single-venue operators in a legend teaches
 *  nothing; saying there are twenty does. 6.68:1. */
export const OTHER_OPERATOR_COLOR = '#7e22ce';

// Hue order is kept from the dark palette so the legend's reading order is unchanged;
// only the lightness moved. Range is 4.78:1 (lime) to 7.56:1 (indigo).
const PALETTE = [
  '#0369a1', // sky      5.68:1
  '#b45309', // amber    4.81:1
  '#047857', // emerald  5.25:1
  '#be185d', // pink     5.78:1
  '#0e7490', // cyan     5.13:1
  '#4d7c0f', // lime     4.78:1
  '#c2410c', // orange   4.96:1
  '#4338ca', // indigo   7.56:1
];

/**
 * Reads the emitted tenure geojson. Only the properties are used — the coordinates are the
 * spine's coordinates by construction, and the spine is already on the map.
 *
 * A missing file is not an error here. The layer ships as `status: 'planned'` precisely
 * because the pipeline may not have produced it yet, and an absent file and an empty
 * FeatureCollection mean the same thing to a reader: no runs on record.
 *
 * Checking the status code is not enough to detect that. The dev server has an SPA fallback,
 * so a request for a file that does not exist comes back as index.html with a 200, and the
 * only tell is the content type. Without this the console reports a JSON parse error where
 * the truth is "the pipeline has not emitted this yet".
 */
export async function loadTenure(src: string): Promise<TenureProperties[]> {
  const res = await fetch(src);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`Failed to load ${src}: ${res.status}`);
  if (!(res.headers.get('content-type') ?? '').includes('json')) return [];
  const raw = (await res.json()) as GeoJSON.FeatureCollection;
  return raw.features.map((f) => f.properties as unknown as TenureProperties);
}

/**
 * Operator -> color, stable across years and re-renders.
 *
 * Ordered by how many runs each operator has, so the operators a reader sees most often keep
 * the same color from session to session. Sorting by name breaks ties, so the assignment does
 * not shuffle when two operators are level.
 */
export function operatorPalette(spans: TenureProperties[]): Map<string, string> {
  const counts = new Map<string, number>();
  for (const s of spans) {
    const op = s.operator_normalized;
    if (!op || op === SELF_OP) continue;
    counts.set(op, (counts.get(op) ?? 0) + 1);
  }

  const ranked = [...counts.entries()].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0])
  );

  const palette = new Map<string, string>([[SELF_OP, SELF_OP_COLOR]]);
  ranked.forEach(([op], i) => {
    palette.set(op, i < PALETTE.length ? PALETTE[i] : OTHER_OPERATOR_COLOR);
  });
  return palette;
}

/** True when this run is on the map in that year. */
function covers(s: TenureProperties, year: number): boolean {
  // An unknown start cannot be placed on a timeline, so it is never painted. It is not
  // dropped either — it stays in the table and in the venue panel, which is where an
  // undated run can still be read.
  if (s.start_year === null || s.render_end_year === null) return false;
  return s.start_year <= year && s.render_end_year >= year;
}

/** venue_id -> the runs covering `year`. Usually one; more than one is the flagged case. */
export function holdersAt(
  spans: TenureProperties[],
  year: number
): Map<string, TenureProperties[]> {
  const held = new Map<string, TenureProperties[]>();
  for (const s of spans) {
    if (!s.venue_id || !covers(s, year)) continue;
    const list = held.get(s.venue_id);
    if (list) list.push(s);
    else held.set(s.venue_id, [s]);
  }
  return held;
}

/**
 * Which run to draw when more than one covers the year, or `null` when the answer is
 * genuinely contested.
 *
 * Two runs can share a year without conflicting: a contract lost on 2011-03-15 and one won
 * on 2011-03-15 are a handoff, and both land in 2011 only because the slider is annual. The
 * full dates survive into the properties, so the handoff is resolved at day resolution and
 * the year gets the operator who actually took over. A real overlap — two operators whose
 * date ranges genuinely intersect — is left contested, because the pipeline flags those
 * rather than picking a winner and the map should not overrule it.
 */
export function holderIn(runs: TenureProperties[]): TenureProperties | null {
  if (runs.length === 1) return runs[0];
  if (new Set(runs.map((r) => r.operator_normalized)).size === 1) return runs[0];

  const sorted = [...runs].sort((a, b) =>
    (a.start_date ?? '').localeCompare(b.start_date ?? '')
  );
  for (let i = 0; i < sorted.length - 1; i += 1) {
    // An open run has no end, so it conflicts with anything that starts after it.
    const end = sorted[i].end_date ?? '9999-12-31';
    if (end > (sorted[i + 1].start_date ?? '9999-12-31')) return null;
  }
  return sorted[sorted.length - 1];
}

/** venue_id -> circle color for `year`. Venues absent from this map stay gray. */
export function venueColorsAt(
  spans: TenureProperties[],
  year: number,
  palette: Map<string, string>
): Map<string, string> {
  const colors = new Map<string, string>();
  for (const [venueId, runs] of holdersAt(spans, year)) {
    const holder = holderIn(runs);
    colors.set(
      venueId,
      holder === null
        ? CONTESTED_COLOR
        : palette.get(holder.operator_normalized ?? '') ?? OTHER_OPERATOR_COLOR
    );
  }
  return colors;
}

export interface LegendEntry {
  operator: string;
  color: string;
  venues: number;
}

/**
 * The legend is a readout of the current year, not a static key: it says who holds how many
 * venues right now. Operators past the palette collapse into one row, because a legend with
 * twenty identically-colored entries is a list, not a legend.
 */
export function operatorLegend(
  spans: TenureProperties[],
  year: number,
  palette: Map<string, string>,
  /** venue_ids actually drawn in this year. A legend that counts venues the map is not
   *  showing — a stadium demolished before `year`, a venue type toggled off — is a legend
   *  that disagrees with the thing it is a legend for. */
  visible: Set<string>
): LegendEntry[] {
  const venuesPerOperator = new Map<string, Set<string>>();
  let contested = 0;

  for (const [venueId, runs] of holdersAt(spans, year)) {
    if (!visible.has(venueId)) continue;
    const holder = holderIn(runs);
    if (holder === null) {
      contested += 1;
      continue;
    }
    const op = holder.operator_normalized ?? 'Unknown operator';
    const set = venuesPerOperator.get(op);
    if (set) set.add(venueId);
    else venuesPerOperator.set(op, new Set([venueId]));
  }

  const named: LegendEntry[] = [];
  let overflow = 0;
  for (const [operator, venues] of venuesPerOperator) {
    const color = palette.get(operator) ?? OTHER_OPERATOR_COLOR;
    if (color === OTHER_OPERATOR_COLOR) overflow += venues.size;
    else named.push({ operator, color, venues: venues.size });
  }

  named.sort((a, b) => b.venues - a.venues || a.operator.localeCompare(b.operator));
  if (overflow) {
    named.push({ operator: 'Other operators', color: OTHER_OPERATOR_COLOR, venues: overflow });
  }
  if (contested) {
    named.push({ operator: 'Two operators at once', color: CONTESTED_COLOR, venues: contested });
  }
  return named;
}

/** Every run at one venue, oldest first, for the detail panel. */
export function runsForVenue(
  spans: TenureProperties[],
  venueId: string | null | undefined
): TenureProperties[] {
  if (!venueId) return [];
  return spans
    .filter((s) => s.venue_id === venueId)
    .sort((a, b) => (a.start_year ?? 9999) - (b.start_year ?? 9999));
}
