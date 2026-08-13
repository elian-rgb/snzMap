/**
 * Contract events — the article pipeline's output, joined onto venues already on the map.
 *
 * This is the only layer in the console built from prose rather than from a government file,
 * so it is also the only one whose coverage is a statement about the corpus rather than about
 * the country. 178 events were extracted; 31 of them name a venue the spine contains, across
 * 7 venues. The other 147 name prisons, school districts and hospitals — real events about
 * real contracts, but not about stadiums, arenas or convention centers, which is what the
 * spine is. That gap is reported in the sidebar rather than quietly dropped, because "we
 * found nothing there" and "we were not looking there" are different claims.
 */
/** One extracted event, as `emit.records` writes it into contract_events.geojson. */
export interface EventProperties {
  event_id: string;
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

/** Every event the pipeline placed at one venue, plus the summary the sidebar prints. */
export interface VenueEvidence {
  venueId: string;
  venueName: string;
  lngLat: [number, number];
  events: EventProperties[];
  operators: string[];
  firstYear: number | null;
  lastYear: number | null;
}

export interface LoadedEvidence {
  venues: VenueEvidence[];
  venueIds: string[];
  /** Events that landed on a venue in this spine. */
  mappedEvents: number;
  /**
   * Every event the extractor produced, mapped or not. Read off the file rather than
   * hardcoded: the console has to say "31 of 178", and a literal in the JSX would keep
   * saying 178 the next time the corpus grows.
   */
  extractedEvents: number;
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

type EventFeature = GeoJSON.Feature<GeoJSON.Point, EventProperties>;

/**
 * Group events by venue.
 *
 * Keyed by venue rather than kept flat because the map draws one ring per venue, not one per
 * event: Drexel alone carries 19 of the 31 events, and 19 rings stacked on one point would
 * read as a single heavy blob that overstates how much of the country this layer covers.
 */
export function buildEvidence(features: EventFeature[], extracted?: number): LoadedEvidence {
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
        events: [],
        operators: [],
        firstYear: null,
        lastYear: null,
      };
      byVenue.set(p.venue_id, v);
    }
    v.events.push(p);
  }

  for (const v of byVenue.values()) {
    // Newest first. A reader scanning a venue's evidence wants the current state of the
    // contract before its history, and an undated event sorts last rather than being
    // dropped — it is still evidence, it just cannot be placed on the timeline.
    v.events.sort((a, b) => (b.event_year ?? -Infinity) - (a.event_year ?? -Infinity));

    v.operators = [...new Set(v.events.map((e) => e.operator_normalized ?? e.operator).filter(Boolean))] as string[];

    const years = v.events.map((e) => e.event_year).filter((y): y is number => typeof y === 'number');
    v.firstYear = years.length ? Math.min(...years) : null;
    v.lastYear = years.length ? Math.max(...years) : null;
  }

  // Most-documented venue first, so the list leads with the one a reader can actually learn
  // something from rather than with whichever venue happened to sort first alphabetically.
  const venues = [...byVenue.values()].sort(
    (a, b) => b.events.length - a.events.length || a.venueName.localeCompare(b.venueName)
  );

  return {
    venues,
    venueIds: venues.map((v) => v.venueId),
    mappedEvents: features.length,
    // Falls back to the mapped count when the file predates the `extracted` field, so an
    // older geojson renders "31 of 31" — understating the corpus — rather than "31 of 0",
    // which would read as a broken denominator and invite the reader to distrust the rest.
    extractedEvents: extracted ?? features.length,
  };
}

export async function loadEvidence(src: string): Promise<LoadedEvidence> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(`${src}: ${res.status}`);
  const fc = (await res.json()) as GeoJSON.FeatureCollection<GeoJSON.Point, EventProperties> & {
    extracted?: number;
  };
  return buildEvidence(fc.features ?? [], fc.extracted);
}

/**
 * Events at a venue that had happened by `year`, for the venue panel.
 *
 * Undated events are always included. An event the article never dated has not been shown to
 * happen after T; it has been shown to happen, full stop. Hiding it while the slider sits in
 * 1994 would let a reader conclude the venue was quiet then, which the source does not say.
 */
export function eventsAsOf(v: VenueEvidence | undefined, year: number): EventProperties[] {
  if (!v) return [];
  return v.events.filter((e) => e.event_year == null || e.event_year <= year);
}
