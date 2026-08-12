/**
 * DOL Wage and Hour enforcement, which has no geography on this map and says so.
 *
 * WHISARD records the employer's establishment address and never a venue name. The federal
 * awards loader can reach a venue because the award *description* names one; there is no
 * equivalent field here. Joining on ZIP alone put 179 in-scope cases across 420 distinct
 * venues — one Raleigh ZIP produced nine NC State venues for a single case — so this layer
 * deliberately stops at the operator. `LaborProfile` has no per-case coordinates and there
 * is no `LaborCase` map feature to go with it.
 *
 * The numbers are also small in a way that matters. $2.1M of back wages across 231 cases and
 * 23 years is a real finding about a real industry, but it is not a headline number, and the
 * panel should not let it read as one by dressing it up with a geography it does not have.
 */

export interface LaborOperator {
  operator: string;
  cases: number;
  back_wages: number;
  employees_due_back_wages: number;
  civil_penalties: number;
  repeat_violator_cases: number;
  first_year: number | null;
  last_year: number | null;
}

export interface LaborProfile {
  source: {
    url: string | null;
    note: string | null;
    fetched_at: string | null;
    candidate_rows: number;
    sha256: string | null;
  };
  venue_join: string;
  cases_in_scope: number;
  back_wages_total: number;
  employees_total: number;
  penalties_total: number;
  by_operator: LaborOperator[];
  scope_counts: Record<string, number>;
  excluded_other_line_top: { naics_description: string; cases: number }[];
  rejected_names_top: { legal_name: string; cases: number }[];
}

/**
 * Same fetch as the federal and tenure layers, for the same reason: the dev server answers a
 * missing file with index.html and a 200, so only the content type distinguishes "not
 * emitted yet" from "emitted and empty".
 */
async function loadJson<T>(src: string): Promise<T | null> {
  const res = await fetch(src);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load ${src}: ${res.status}`);
  if (!(res.headers.get('content-type') ?? '').includes('json')) return null;
  return (await res.json()) as T;
}

export async function loadLaborProfile(src: string): Promise<LaborProfile | null> {
  return loadJson<LaborProfile>(src);
}

/**
 * The span the panel puts under its headline, derived from the operator rows rather than
 * written into the prose. A hand-written "2001–2024" is a claim about the data that goes
 * stale the next time the snapshot is refreshed and nobody notices, which is exactly how the
 * federal sidebar came to name one convention centre under a headline that said three.
 */
export function yearSpan(ops: LaborOperator[]): string {
  const first = ops.map((o) => o.first_year).filter((y): y is number => y != null);
  const last = ops.map((o) => o.last_year).filter((y): y is number => y != null);
  if (!first.length || !last.length) return '';
  return `${Math.min(...first)}–${Math.max(...last)}`;
}

/**
 * Cases the pipeline looked at and threw away, as a share of everything it fetched.
 *
 * Surfaced because it is the honest half of this layer. 493 of 840 candidate rows are
 * companies that merely *look* like an operator by substring — Compass Bank alone is 80 —
 * and a panel that reports only the 231 survivors invites the reader to assume the query was
 * clean. It was not; it was made clean.
 */
export function rejectionRate(p: LaborProfile): number {
  const total = Object.values(p.scope_counts).reduce((s, n) => s + n, 0);
  return total ? (p.scope_counts.rejected_not_an_operator ?? 0) / total : 0;
}

/** Operators carrying at least one case, largest back-wage total first. */
export function operatorsByBackWages(p: LaborProfile): LaborOperator[] {
  return [...p.by_operator].sort((a, b) => b.back_wages - a.back_wages);
}

/** Whole dollars with separators. Unlike the federal panel there is nothing here big enough
 *  to need compacting — the largest single figure is $793,347 — and rounding $1,892 to $2K
 *  would hide that one of these operators has a single case worth less than a week's pay. */
export function dollars(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return `$${Math.round(n).toLocaleString('en-US')}`;
}

/** The mirror's hostname, for the provenance line. The console says where the data actually
 *  came from rather than implying dol.gov served it, because dol.gov did not: its own API
 *  requires a registered key and this is an independent rebuild of the same public records. */
export function sourceHost(p: LaborProfile): string {
  try {
    return new URL(p.source.url ?? '').hostname;
  } catch {
    return p.source.url ?? 'unknown';
  }
}
