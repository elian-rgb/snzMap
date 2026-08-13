/**
 * One operator, everything this console actually knows about it.
 *
 * The console holds three unrelated things per operator — federal contract spending, DOL wage
 * & hour enforcement, and venue-level awards — and before this they were three panels a
 * reader had to join in their head. This merges them into one object per operator so the
 * question "what do we have on Aramark" has a single answer.
 *
 * **The join is by operator name and nothing else, and that is the whole caveat.** These are
 * three federal datasets that never reference each other. A row here means the same normalized
 * operator name appeared in each source, not that the same contract, site or legal entity did.
 *
 * The number that must never be misread is `obligated`. Sodexo's $4.99B is food service at
 * military posts, federal buildings and VA hospitals. It is real money and real reporting, and
 * it is **not** venue concession revenue — almost none of it happens at a place in this spine.
 * `venueAwards` is the honest subset: awards that actually name a spine venue, of which there
 * are 8 in total. Every consumer of this module is expected to show both and never the first
 * alone, which is why `obligated` and `venueObligated` are separate fields rather than one
 * number with a footnote.
 */

import type { FederalAward, FederalProfile } from './federalTransform';
import type { LaborProfile } from './laborTransform';

export interface OperatorRow {
  operator: string;
  /** Federal food-service awards anywhere — mostly NOT venues. See module note. */
  federalAwards: number;
  obligated: number;
  /** The subset that names a venue in this spine. Small on purpose. */
  venueAwards: number;
  venueObligated: number;
  venueNames: string[];
  /** Concluded DOL WHD cases. Not venue-attributable — WHISARD records no venue. */
  cases: number;
  backWages: number;
  employees: number;
  repeatCases: number;
  firstYear: number | null;
  lastYear: number | null;
  /** True when at least one source has something. A row with none is not built. */
  hasAny: boolean;
}

/**
 * Every operator named by any source, merged.
 *
 * Union rather than intersection: 9 operators appear in the wage & hour data and only 4 in the
 * federal data, and dropping the 5 that appear in one source would hide real enforcement
 * history to make a table look uniform.
 */
export function buildOperatorRows(
  federal: FederalProfile | null,
  labor: LaborProfile | null,
  venueAwards: FederalAward[]
): OperatorRow[] {
  const names = new Set<string>();
  for (const f of federal?.by_operator ?? []) names.add(f.operator);
  for (const l of labor?.by_operator ?? []) names.add(l.operator);

  const rows: OperatorRow[] = [];
  for (const operator of names) {
    const f = federal?.by_operator?.find((x) => x.operator === operator);
    const l = labor?.by_operator?.find((x) => x.operator === operator);
    const mine = venueAwards.filter((a) => a.operator === operator);

    rows.push({
      operator,
      federalAwards: f?.awards ?? 0,
      obligated: f?.obligated ?? 0,
      venueAwards: mine.length,
      venueObligated: mine.reduce((s, a) => s + (a.obligated_amount ?? 0), 0),
      // `venue_name` is nullable in the awards file, though all 8 current awards carry one.
      // An unnamed award is dropped from this list but still counted in `venueAwards` — the
      // award is real whether or not the join produced a printable name.
      venueNames: [...new Set(mine.map((a) => a.venue_name).filter((n): n is string => !!n))],
      cases: l?.cases ?? 0,
      backWages: l?.back_wages ?? 0,
      employees: l?.employees_due_back_wages ?? 0,
      repeatCases: l?.repeat_violator_cases ?? 0,
      firstYear: l?.first_year ?? null,
      lastYear: l?.last_year ?? null,
      hasAny: Boolean(f || l),
    });
  }

  // Back wages first: this console is about who works in these buildings, and an operator with
  // enforcement history is the more consequential row. Federal dollars break ties because the
  // 5 operators with no federal awards at all would otherwise sort arbitrarily.
  return rows.sort(
    (a, b) => b.backWages - a.backWages || b.obligated - a.obligated
  );
}

/** Venue ids this operator is documented at. The only defensible way to put it on a map. */
export function venueIdsForOperator(
  venueAwards: FederalAward[],
  operator: string | null
): Set<string> {
  if (!operator) return new Set();
  return new Set(
    venueAwards.filter((a) => a.operator === operator).map((a) => a.venue_id)
  );
}
