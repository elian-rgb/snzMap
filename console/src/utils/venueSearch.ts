/**
 * Find a venue by the name someone actually types.
 *
 * The spine has 6,884 dots and no way to reach a specific one except by zooming to the right
 * city and clicking. That makes "is Madison Square Garden in here?" an unanswerable question
 * from the UI even though the answer is yes, three times over.
 *
 * Searching aliases rather than only `canonical_name` is the whole point. The spine stores
 * the *current* name, so a search for "Staples Center" against canonical names alone returns
 * nothing while Crypto.com Arena sits right there — and a reader would reasonably conclude
 * the venue is missing. Every alias is a match key, and the hit reports which name matched
 * so a surprising result explains itself.
 */

import { nameAtYear, type VenueProperties } from './spineTransform';

export interface VenueHit {
  venue: VenueProperties;
  lngLat: [number, number];
  /** The name that matched, which may be an old one the venue no longer uses. */
  matched: string;
  /** True when `matched` is not the venue's current name, so the UI can say why. */
  viaAlias: boolean;
}

/** Case- and accent-insensitive, punctuation-stripped.
 *
 *  Folding is not cosmetic here: the spine spells it "Henry B. González Convention Center"
 *  and nobody types the accent. Apostrophes go the same way, so "Levis Stadium" finds
 *  "Levi's Stadium" — the two spellings are equally likely from a keyboard. */
function fold(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Common shorthands that are not in the spine's alias list because no source publishes
 *  them as names. They are initialisms a person types, not names a venue has. */
const SHORTHAND: Record<string, string> = {
  msg: 'madison square garden',
  sofi: 'sofi stadium',
  'the garden': 'madison square garden',
};

/**
 * Ranked matches, best first.
 *
 * Ranking is prefix > word-boundary > substring, then capacity as the tiebreak. Capacity is
 * the tiebreak for the same reason `candidates.py` uses it: 30 venues own "memorial stadium",
 * and alphabetical truncation drops the 56,000-seat one while keeping a 6,516-seat one. A
 * person typing a bare name almost always means the big one.
 */
export function searchVenues(
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null,
  query: string,
  limit = 8
): VenueHit[] {
  const q = SHORTHAND[fold(query)] ?? fold(query);
  if (!spine || q.length < 2) return [];

  const scored: { hit: VenueHit; score: number }[] = [];
  for (const f of spine.features) {
    const v = f.properties;
    let best: { score: number; matched: string; viaAlias: boolean } | null = null;

    const names: [string, boolean][] = [[v.canonical_name, false]];
    for (const a of v.aliases) if (a.name) names.push([a.name, true]);

    for (const [name, viaAlias] of names) {
      const folded = fold(name);
      let score: number;
      if (folded === q) score = 0;
      else if (folded.startsWith(q)) score = 1;
      else if (folded.includes(` ${q}`)) score = 2;
      else if (folded.includes(q)) score = 3;
      else continue;
      // A canonical-name hit outranks an alias hit at the same quality, so searching
      // "Wrigley Field" surfaces the venue itself before another venue that once
      // carried the name as an alias.
      score = score * 2 + (viaAlias ? 1 : 0);
      if (!best || score < best.score) best = { score, matched: name, viaAlias };
    }

    if (best) {
      scored.push({
        hit: {
          venue: v,
          lngLat: f.geometry.coordinates as [number, number],
          matched: best.matched,
          viaAlias: best.viaAlias,
        },
        score: best.score,
      });
    }
  }

  scored.sort(
    (a, b) =>
      a.score - b.score ||
      (b.hit.venue.capacity ?? 0) - (a.hit.venue.capacity ?? 0) ||
      a.hit.venue.canonical_name.localeCompare(b.hit.venue.canonical_name)
  );
  return scored.slice(0, limit).map((s) => s.hit);
}

/** What to show under a hit so two venues with the same name are distinguishable.
 *
 *  This matters more than it looks: there are three Madison Square Gardens and two Wrigley
 *  Fields, and a result list that prints the name alone makes the user pick blind. */
export function hitSubtitle(hit: VenueHit, year: number): string {
  const v = hit.venue;
  const place = [v.city, v.state].filter(Boolean).join(', ');
  const span = v.opened_date
    ? `${v.opened_date.slice(0, 4)}\u2013${v.closed_date ? v.closed_date.slice(0, 4) : ''}`
    : v.closed_date
      ? `closed ${v.closed_date.slice(0, 4)}`
      : '';
  // Compared against the name the row actually prints — `canonical_name` — not against the
  // name in use at `year`. Searching "Staples Center" at 2015 returns a row titled
  // "Crypto.com Arena", and comparing against nameAtYear suppressed the explanation in
  // exactly that case, because the venue really was called Staples Center in 2015. The
  // reader is left to guess why their query matched.
  const via =
    hit.viaAlias && fold(hit.matched) !== fold(v.canonical_name)
      ? `matched \u201c${hit.matched}\u201d`
      : '';
  // Only worth saying when it disagrees with the title; otherwise it is the title again.
  const nameNow = nameAtYear(v, year);
  const thenName =
    fold(nameNow) !== fold(v.canonical_name) && fold(nameNow) !== fold(hit.matched)
      ? `${nameNow} in ${year}`
      : '';
  return [place, span, via, thenName].filter(Boolean).join(' \u00b7 ');
}
