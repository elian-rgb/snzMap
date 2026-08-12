/**
 * Shades the ZCTA around each venue by one ACS measure.
 *
 * Three decisions here are worth stating, because each could reasonably have gone the other
 * way and the wrong one would put a false trend on screen.
 *
 * **Some measures are ranked within the year and some are on a scale fixed across all years,
 * and which is which was decided by measuring the data.** Median household income in this
 * data is nominal — the 2011 figure is in 2011 dollars, the 2024 figure in 2024 dollars, and
 * nothing deflates it (see `income_note` shipped with the ACS file). Its 20th percentile ran
 * $35,361 in 2011 to $54,905 in 2024, which is mostly inflation, so a fixed dollar ramp would
 * turn the map steadily warmer and a reader would see neighbourhoods getting richer. Ranking
 * within each year removes that.
 *
 * The same treatment applied to the other three would be a worse error in the opposite
 * direction. Transit share is a ratio, directly comparable between years, and it *fell*: the
 * median venue neighbourhood went from 1.45% of workers commuting by transit in 2011 to 0.83%
 * in 2024, and the 80th percentile from 6.8% to 4.0%. Ranking that within each year would
 * hold every bin at a fifth of the ZCTAs forever and render the single largest real movement
 * in this dataset perfectly invisible. So ratios and counts get one set of cutoffs, computed
 * once from every year pooled and applied unchanged to each year — color means an amount, the
 * bin counts move, and the fall is what you see.
 *
 * **Only ZCTAs with a venue are drawn.** The shape file contains 4,087 of the country's
 * ~33,000 ZCTAs. Blank is not missing data — it is "no venue here". That claim is only
 * honest because the blank is the same everywhere; a national choropleth with holes would
 * read as a coverage failure instead.
 */

import type { AcsContext } from './acsTransform';

/** ACS 5-year vintages through this year are tabulated on 2010-Census ZCTAs. */
const LAST_2010_VINTAGE = 2020;

/**
 * Sequential, light to medium. Deliberately blue-gray and low-chroma: the venue dots on top
 * are a categorical operator palette, and a saturated choropleth would compete with them for
 * the same attention while meaning something completely different.
 *
 * It stops at medium rather than running to a dark end, and that ceiling is the constraint
 * the light theme imposed. The dots are dark on a light map, so a dark fifth bin would
 * swallow them, and since tenure has no runs today *every* dot is NO_DATA — the top bin would
 * erase the entire venue layer exactly where the data is densest.
 *
 * These values are not what the eye gets. The layer draws at `fill-opacity: 0.55`, so each bin
 * is composited over positron's #fafaf8 land before anyone sees it, and the rendered ramp is
 * much lighter than the hex above. An earlier version of this comment claimed a 3.10:1 worst
 * case; that number was measured on the raw hex and was wrong. Composited, the honest figures
 * for NO_DATA_COLOR (#64748b, the binding dot because it is currently the only one) are:
 *
 *   bin  raw       composited   dot vs bin
 *    1   #f2f6fa   #f6f9fb        4.47:1
 *    2   #dde8f3   #eaf0f6        4.14:1
 *    3   #c4d8ea   #dde8f2        3.79:1
 *    4   #a7c3de   #cdddec        3.40:1
 *    5   #88add2   #bccfe4        3.00:1
 *
 * The dark end was lifted from #6b96c4 to #88add2 to get that last row over 3:1. It cost the
 * ramp real range — end to end the composited spread fell from 1.67:1 to 1.49:1, and adjacent
 * bins now differ by 1.08–1.13:1. That is a bad ramp considered on its own. It is the right
 * trade here because the legend carries the exact cutoffs, so the shading only has to show
 * direction, whereas a dot that fails 1.4.11 over the top bin is information that is simply
 * not there for some readers. Direction is recoverable from a weak ramp; a missing venue is not.
 */
const RAMP = ['#f2f6fa', '#dde8f3', '#c4d8ea', '#a7c3de', '#88add2'];

/** Drawn for a ZCTA that has a polygon but no estimate this year. Warm and off-scale on
 *  purpose — it is the one color here that is not part of the sequence, so "no estimate"
 *  cannot be read as "lowest bin". Lightened from #bfa77f for the same reason the ramp's dark
 *  end was: composited it left the dots at 3.01:1, which passes only by rounding. 3.30:1 now,
 *  and 1.04:1 against the top bin — nowhere near the blue family. */
export const NO_VALUE_COLOR = '#cbb894';

export type MetricKey =
  | 'median_household_income'
  | 'transit_share'
  | 'long_commute_share'
  | 'workers_total';

/**
 * `rank` recomputes cutoffs from the year's own values; `fixed` uses one set of cutoffs
 * derived from every year pooled. See the module note — this is the whole design, not a
 * rendering preference.
 */
export type ScaleMode = 'rank' | 'fixed';

export interface MetricDef {
  key: MetricKey;
  label: string;
  scale: ScaleMode;
  format: (n: number) => string;
  /** Why this measure is scaled the way it is, printed under the legend. */
  note: string;
}

const dollars = (n: number) =>
  n >= 1000 ? `$${Math.round(n / 1000)}k` : `$${Math.round(n)}`;

/** One decimal below 10%, because transit share spends most of its range under 7% and
 *  rounding to whole percent would collapse three of the five bins into "0%". */
const percent = (n: number) => {
  const p = n * 100;
  return p < 10 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`;
};

const count = (n: number) =>
  n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;

export const METRICS: MetricDef[] = [
  {
    key: 'median_household_income',
    label: 'Median household income',
    scale: 'rank',
    format: dollars,
    note:
      'Cutoffs are that year\u2019s own dollars and are not deflated, so they move between ' +
      'years and a color is a rank against the other venue neighbourhoods, not an amount.',
  },
  {
    key: 'transit_share',
    label: 'Commute by transit',
    scale: 'fixed',
    format: percent,
    note:
      'One scale for every year, so a color is the same share whenever you see it and the ' +
      'bin counts move instead. They move a lot: the median venue neighbourhood fell from ' +
      '1.5% in 2011 to 0.8% in 2024.',
  },
  {
    key: 'long_commute_share',
    // 45, not 60: the pipeline sums B08303_011E (45-59 min), _012E (60-89) and _013E (90+).
    // The venue panel has always said 45; this label said 60 for one commit.
    label: 'Commute 45 min or more',
    scale: 'fixed',
    format: percent,
    note:
      'One scale for every year, so a color is the same share whenever you see it and the ' +
      'bin counts move instead.',
  },
  {
    key: 'workers_total',
    label: 'Workers living here',
    scale: 'fixed',
    format: count,
    note:
      'Workers resident in the ZIP area, not employed at the venue. One scale for every ' +
      'year. This is a size measure \u2014 a large ZIP area will rank high for being large.',
  },
];

export const METRIC_BY_KEY: Record<MetricKey, MetricDef> = Object.fromEntries(
  METRICS.map((m) => [m.key, m])
) as Record<MetricKey, MetricDef>;

export interface ZctaShapes {
  vintage: number;
  features: GeoJSON.FeatureCollection;
  scopeNote: string;
  crsNote: string;
}

export interface ChoroplethBin {
  color: string;
  /** Inclusive lower bound of this bin, in the metric's own units. */
  min: number;
  max: number;
  zctas: number;
}

export interface Choropleth {
  /** zcta -> color, ready to become a GL `match` expression. */
  colors: Map<string, string>;
  /** zcta -> the raw figure behind the color, for hover and the detail panel. A ZCTA that is
   *  drawn but absent here is one ACS published no estimate for this year. */
  values: Map<string, number>;
  bins: ChoroplethBin[];
  /** ZCTAs drawn this year with no estimate behind them. */
  withoutValue: number;
  vintage: number;
  metric: MetricDef;
  /** The years ACS actually published, sorted. Carried here so that a slider year outside
   *  them can be named on screen as the reason nothing is shaded, rather than the legend
   *  quietly disappearing — the slider runs 1850–2026 and this runs 2011–2024, so the
   *  uncovered case is the common one. */
  years: number[];
}

/** Which ZCTA definition a slider year is published on. */
export function vintageForYear(year: number): number {
  return year <= LAST_2010_VINTAGE ? 2010 : 2020;
}

export async function loadZctaShapes(
  srcPrefix: string,
  vintage: number
): Promise<ZctaShapes | null> {
  const res = await fetch(`${srcPrefix}${vintage}.geojson`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load ZCTA shapes: ${res.status}`);
  // Same content-type guard the other loaders use: the dev server answers a missing file
  // with index.html and a 200, so status alone cannot tell "absent" from "empty".
  if (!(res.headers.get('content-type') ?? '').includes('json')) return null;
  const raw = await res.json();
  return {
    vintage,
    features: raw as GeoJSON.FeatureCollection,
    scopeNote: raw.scope_note ?? '',
    crsNote: raw.crs_note ?? '',
  };
}

/**
 * ZCTA -> one measure for one year.
 *
 * The ACS payload is keyed by venue, not by ZCTA, so this inverts it. Several venues can
 * share a ZCTA — they then carry identical figures, because the figure was never about the
 * venue in the first place — so the first one wins and the rest are consistent by
 * construction rather than by averaging something that is already one number.
 */
export function valueByZcta(
  acs: AcsContext | null,
  year: number,
  metric: MetricKey
): Map<string, number> {
  const out = new Map<string, number>();
  if (!acs) return out;
  const column = acs.series_columns.indexOf(metric);
  if (column === -1) return out;
  const vintage = vintageForYear(year);

  for (const venue of Object.values(acs.venues)) {
    const code = vintage === 2010 ? venue.zcta_2010 : venue.zcta_2020;
    if (!code || out.has(code)) continue;
    const row = venue.years[String(year)];
    const value = row?.[column];
    if (typeof value === 'number') out.set(code, value);
  }
  return out;
}

/**
 * Every value this measure takes in any year, sorted — the reference distribution for a
 * `fixed` metric.
 *
 * Pooled across years *and* both ZCTA vintages on purpose. Cutoffs that depended on which
 * vintage was loaded would shift when the slider crossed 2020, which is exactly the silent
 * movement a fixed scale exists to rule out. Cached because it walks ~96,000 venue-years.
 */
const pooledCache = new WeakMap<AcsContext, Partial<Record<MetricKey, number[]>>>();

export function pooledValues(acs: AcsContext | null, metric: MetricKey): number[] {
  if (!acs) return [];
  let byMetric = pooledCache.get(acs);
  if (!byMetric) {
    byMetric = {};
    pooledCache.set(acs, byMetric);
  }
  const hit = byMetric[metric];
  if (hit) return hit;

  const column = acs.series_columns.indexOf(metric);
  const values: number[] = [];
  if (column !== -1) {
    // Deduplicated per year, so a ZCTA holding six venues does not get six votes in the
    // cutoffs — the same rule `valueByZcta` applies within a year.
    const seen = new Set<string>();
    for (const venue of Object.values(acs.venues)) {
      for (const [yearKey, row] of Object.entries(venue.years)) {
        const year = Number(yearKey);
        const code = vintageForYear(year) === 2010 ? venue.zcta_2010 : venue.zcta_2020;
        if (!code) continue;
        const id = `${year}:${code}`;
        if (seen.has(id)) continue;
        seen.add(id);
        const value = row[column];
        if (typeof value === 'number') values.push(value);
      }
    }
  }
  values.sort((a, b) => a - b);
  byMetric[metric] = values;
  return values;
}

/**
 * Five bins for one year and one measure.
 *
 * For a `rank` metric the cutoffs come from the values present this year, so a year where
 * ACS published less does not silently shift everything into the bottom bins. For a `fixed`
 * metric they come from every year pooled and do not move at all — which is the point, since
 * the counts moving between bins is then a real change rather than an artifact of rescaling.
 */
export function choroplethFor(
  acs: AcsContext | null,
  year: number,
  drawnZctas: Set<string> | null,
  metricKey: MetricKey
): Choropleth {
  const metric = METRIC_BY_KEY[metricKey];
  const vintage = vintageForYear(year);
  const values = valueByZcta(acs, year, metricKey);
  const years = acs?.years ?? [];

  const usable = [...values.entries()].filter(
    ([code]) => !drawnZctas || drawnZctas.has(code)
  );

  const colors = new Map<string, string>();
  const bins: ChoroplethBin[] = [];

  // The distribution the cutoffs are read off. For `fixed` this is every year at once, so it
  // is identical on every frame; for `rank` it is only what is on screen right now.
  const reference =
    metric.scale === 'fixed'
      ? pooledValues(acs, metricKey)
      : usable.map(([, v]) => v).sort((a, b) => a - b);

  if (reference.length === 0 || usable.length === 0) {
    return {
      colors,
      values: new Map(usable),
      bins,
      withoutValue: drawnZctas?.size ?? 0,
      vintage,
      metric,
      years,
    };
  }

  // Cut points at the 20th, 40th, 60th and 80th percentiles of the reference distribution.
  const cuts = [1, 2, 3, 4].map((i) => reference[Math.floor((reference.length * i) / 5)]);
  const binOf = (v: number) => {
    let i = 0;
    while (i < cuts.length && v >= cuts[i]) i += 1;
    return i;
  };

  const counts = new Array(RAMP.length).fill(0);
  for (const [code, value] of usable) {
    const i = binOf(value);
    colors.set(code, RAMP[i]);
    counts[i] += 1;
  }

  for (let i = 0; i < RAMP.length; i += 1) {
    bins.push({
      color: RAMP[i],
      min: i === 0 ? reference[0] : cuts[i - 1],
      max: i === RAMP.length - 1 ? reference[reference.length - 1] : cuts[i],
      zctas: counts[i],
    });
  }

  const withoutValue = drawnZctas
    ? [...drawnZctas].filter((c) => !colors.has(c)).length
    : 0;

  return { colors, values: new Map(usable), bins, withoutValue, vintage, metric, years };
}

/** One ZCTA's four figures for one year, plus the venues that put it on the map. */
export interface ZctaDetail {
  zcta: string;
  vintage: number;
  year: number;
  /** All four measures, in `METRICS` order. `null` is "ACS published none for this year",
   *  which the panel prints as such rather than as a blank. */
  values: { metric: MetricDef; value: number | null }[];
  /** Why this polygon is drawn at all — the layer is venue ZCTAs only. */
  venueIds: string[];
}

/**
 * Everything known about one ZCTA in one year.
 *
 * Walks the venue-keyed payload rather than an index, because this runs on click — once per
 * user action, not per frame — and an index would be a second copy of the data to keep in
 * step with the vintage.
 */
export function zctaDetail(
  acs: AcsContext | null,
  year: number,
  code: string
): ZctaDetail | null {
  const vintage = vintageForYear(year);
  const detail: ZctaDetail = {
    zcta: code,
    vintage,
    year,
    values: METRICS.map((metric) => ({ metric, value: null as number | null })),
    venueIds: [],
  };
  if (!acs) return detail;

  let row: (number | null)[] | undefined;
  for (const [venueId, venue] of Object.entries(acs.venues)) {
    const venueCode = vintage === 2010 ? venue.zcta_2010 : venue.zcta_2020;
    if (venueCode !== code) continue;
    detail.venueIds.push(venueId);
    // Every venue in a ZCTA carries the same figures — the figures were never about the
    // venue — so the first row found is the ZCTA's row, not one venue's version of it.
    row ??= venue.years[String(year)];
  }

  if (row) {
    for (const entry of detail.values) {
      const column = acs.series_columns.indexOf(entry.metric.key);
      const value = column === -1 ? null : row[column];
      entry.value = typeof value === 'number' ? value : null;
    }
  }
  return detail;
}
