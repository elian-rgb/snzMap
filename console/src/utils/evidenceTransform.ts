/**
 * Contract events — the article pipeline's output, joined onto venues already on the map.
 *
 * This is the only layer in the console built from prose rather than from a government file,
 * so it is also the only one whose coverage is a statement about the corpus rather than about
 * the country. Most extracted events name prisons, school districts and hospitals — real
 * events about real contracts, but not about stadiums, arenas or convention centers, which is
 * what the spine is. That gap is reported in the sidebar rather than quietly dropped, because
 * "we found nothing there" and "we were not looking there" are different claims. Every figure
 * in that sentence is read off the file; none is written here, because a number in a comment
 * or in JSX stops being true the next time the corpus grows.
 *
 * A feature is a *claim*, not an article sentence. `emit.records` folds repeat coverage of one
 * award into one feature carrying `mentions`, so four papers reporting the Drexel contract are
 * one pin corroborated four times rather than four contracts. The three counts on the
 * collection are all needed and all different: `extracted` is every event, `mapped` is the
 * events that landed on a venue in this spine, `claims` is how many distinct things those
 * events say.
 */
/** One claim, as `emit.records` writes it into contract_events.geojson. */
export interface ClaimProperties {
  event_id: string;
  /** How many extracted events state this claim. 1 means a single uncorroborated report. */
  mentions: number;
  event_ids: string[];
  sources: string[];
  venue_id: string | null;
  venue_name: string | null;
  venue_name_as_written: string | null;
  operator: string | null;
  operator_normalized: string | null;
  sub_brand: string | null;
  event_type: string;
  event_date: string | null;
  event_year: number | null;
  date_precision: string | null;
  contract_value_usd: number | null;
  extraction_confidence: number | null;
  needs_review: boolean;
  source_publication: string | null;
  source_date: string | null;
  source_title: string | null;
}

/** Every claim the pipeline placed at one venue, plus the summary the sidebar prints. */
export interface VenueEvidence {
  venueId: string;
  venueName: string;
  lngLat: [number, number];
  claims: ClaimProperties[];
  /** Extracted events behind those claims — always >= claims.length. */
  mentions: number;
  operators: string[];
  firstYear: number | null;
  lastYear: number | null;
}

export interface LoadedEvidence {
  venues: VenueEvidence[];
  venueIds: string[];
  /** Events that landed on a venue in this spine. */
  mappedEvents: number;
  /** Distinct claims those events make — the number of features actually drawn. */
  mappedClaims: number;
  /**
   * Every event the extractor produced, mapped or not. Read off the file rather than
   * hardcoded: the console has to state a coverage fraction, and a literal in the JSX would
   * keep quoting today's corpus after the corpus has grown.
   */
  extractedEvents: number;
  /** Precision audit, or null if nobody has run one. Null renders as "unaudited". */
  audit: AuditSummary | null;
}

/**
 * Result of `pipeline.audit.score` — a hand-judged random sample of extracted events, each
 * checked against the article it came from.
 *
 * `ci95` is carried and displayed rather than dropped, because the point estimate alone is
 * not honest at this sample size: 14 of 20 is "70%", but the data only supports "somewhere
 * between 48% and 86%". Showing the bare 70% would be exactly the wrong-big-number failure
 * this console exists to avoid.
 */
export interface AuditSummary {
  judged: number;
  correct: number;
  precision: number | null;
  ci95: [number, number] | null;
  /** False when the pipeline's own author judged the rows. */
  independent: boolean;
  /** False when too few rows were judged for the interval to mean anything. */
  is_a_measurement: boolean;
}

/**
 * Ring color for a venue an article speaks to. 7.88:1 on positron land, 5.83:1 on water —
 * a coastal stadium sits on the boundary, so passing on land alone is not passing.
 *
 * Magenta rather than another amber: the federal ring is #854d0e, and "a government contract
 * names this venue" and "a newspaper names this venue" are different claims that must not
 * read as the same mark. The two also differ in radius, which is the part that survives a
 * grayscale print — every color in this console is now within ~1.2 luminance of some other
 * color in it, so hue alone can no longer carry a distinction by itself.
 */
export const EVIDENCE_COLOR = '#86198f';

type ClaimFeature = GeoJSON.Feature<GeoJSON.Point, ClaimProperties>;

/**
 * Group claims by venue.
 *
 * Keyed by venue rather than kept flat because the map draws one ring per venue, not one per
 * claim: Drexel alone carries 8 of the 18 claims, and stacked rings on one point would read
 * as a single heavy blob that overstates how much of the country this layer covers.
 */
export function buildEvidence(
  features: ClaimFeature[],
  extracted?: number,
  mapped?: number,
  audit: AuditSummary | null = null
): LoadedEvidence {
  const byVenue = new Map<string, VenueEvidence>();

  for (const f of features) {
    const p = f.properties;
    if (!p.venue_id) continue;

    let v = byVenue.get(p.venue_id);
    if (!v) {
      v = {
        venueId: p.venue_id,
        venueName: p.venue_name ?? p.venue_name_as_written ?? p.venue_id,
        lngLat: f.geometry.coordinates as [number, number],
        claims: [],
        mentions: 0,
        operators: [],
        firstYear: null,
        lastYear: null,
      };
      byVenue.set(p.venue_id, v);
    }
    v.claims.push(p);
    // `?? 1` so a geojson written before this field existed counts one mention per claim
    // rather than reporting zero sources for evidence that plainly has one.
    v.mentions += p.mentions ?? 1;
  }

  for (const v of byVenue.values()) {
    // Newest first. A reader scanning a venue's evidence wants the current state of the
    // contract before its history, and an undated claim sorts last rather than being
    // dropped — it is still evidence, it just cannot be placed on the timeline.
    v.claims.sort((a, b) => (b.event_year ?? -Infinity) - (a.event_year ?? -Infinity));

    v.operators = [...new Set(v.claims.map((e) => e.operator_normalized ?? e.operator).filter(Boolean))] as string[];

    const years = v.claims.map((e) => e.event_year).filter((y): y is number => typeof y === 'number');
    v.firstYear = years.length ? Math.min(...years) : null;
    v.lastYear = years.length ? Math.max(...years) : null;
  }

  // Most-documented venue first, so the list leads with the one a reader can actually learn
  // something from rather than with whichever venue happened to sort first alphabetically.
  // Ties break on mentions: two venues with three claims each are not equally documented if
  // one of them was corroborated by six papers and the other by three.
  const venues = [...byVenue.values()].sort(
    (a, b) =>
      b.claims.length - a.claims.length ||
      b.mentions - a.mentions ||
      a.venueName.localeCompare(b.venueName)
  );

  const mappedClaims = features.length;
  return {
    venues,
    venueIds: venues.map((v) => v.venueId),
    // Both fall back to what the file can still support when it predates these fields. An
    // older geojson then understates the corpus rather than rendering a zero denominator,
    // which would read as broken and invite the reader to distrust the rest.
    mappedEvents: mapped ?? mappedClaims,
    mappedClaims,
    extractedEvents: extracted ?? mapped ?? mappedClaims,
    audit,
  };
}

export async function loadEvidence(src: string, auditSrc?: string): Promise<LoadedEvidence> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(`${src}: ${res.status}`);
  const fc = (await res.json()) as GeoJSON.FeatureCollection<GeoJSON.Point, ClaimProperties> & {
    extracted?: number;
    mapped?: number;
  };

  // A missing or unreadable audit is not an error — it means nobody has run one, which the
  // sidebar says out loud. Letting it reject would take the whole evidence layer down with
  // it and hide 31 real events over a missing quality report.
  let audit: AuditSummary | null = null;
  if (auditSrc) {
    try {
      const a = await fetch(auditSrc);
      if (a.ok) {
        const parsed = (await a.json()) as AuditSummary;
        audit = parsed.is_a_measurement ? parsed : null;
      }
    } catch {
      audit = null;
    }
  }

  return buildEvidence(fc.features ?? [], fc.extracted, fc.mapped, audit);
}

/**
 * Claims at a venue that had happened by `year`, for the venue panel.
 *
 * Undated claims are always included. A claim the article never dated has not been shown to
 * happen after T; it has been shown to happen, full stop. Hiding it while the slider sits in
 * 1994 would let a reader conclude the venue was quiet then, which the source does not say.
 */
export function claimsAsOf(v: VenueEvidence | undefined, year: number): ClaimProperties[] {
  if (!v) return [];
  return v.claims.filter((e) => e.event_year == null || e.event_year <= year);
}
