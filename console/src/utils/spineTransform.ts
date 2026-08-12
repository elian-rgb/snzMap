/**
 * Loads the venue spine and prepares it for MapLibre.
 *
 * The one real transform is date -> year. GL filter expressions have no date type, so
 * `opened_date: "1976-03-27"` cannot be compared to a slider value. Precomputing an
 * `opened_year` number means the time slider is a numeric comparison in the GL layer
 * rather than a JS pass over 7k features on every tick.
 */

export interface VenueAlias {
  name: string;
  start_date: string | null;
  end_date: string | null;
  dated: boolean;
}

export interface VenueProperties {
  venue_id: string;
  canonical_name: string;
  venue_type: string;
  city: string | null;
  state: string | null;
  opened_date: string | null;
  closed_date: string | null;
  opened_year: number | null;
  closed_year: number | null;
  capacity: number | null;
  wikidata_qid: string | null;
  osm_id: string | null;
  spine_source: string;
  coord_delta_km: number | null;
  name_is_ambiguous: boolean;
  aliases: VenueAlias[];
}

function year(date: string | null | undefined): number | null {
  if (!date) return null;
  const y = Number.parseInt(date.slice(0, 4), 10);
  return Number.isFinite(y) ? y : null;
}

export async function loadSpine(
  src: string
): Promise<GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties>> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(`Failed to load ${src}: ${res.status}`);
  const raw = (await res.json()) as GeoJSON.FeatureCollection<GeoJSON.Point>;

  const features = raw.features.map((f) => {
    const p = f.properties as Record<string, unknown>;
    // Wikidata carries aliases as an array; GL sources flatten nested values, so keep the
    // parsed form on the JS side and hand the GL source only the scalars it can filter on.
    const aliases = (p.aliases as VenueAlias[]) ?? [];
    return {
      ...f,
      properties: {
        ...p,
        aliases,
        opened_year: year(p.opened_date as string | null),
        closed_year: year(p.closed_date as string | null),
      } as unknown as VenueProperties,
    };
  });

  return { type: 'FeatureCollection', features } as GeoJSON.FeatureCollection<
    GeoJSON.Point,
    VenueProperties
  >;
}

/**
 * Venue types present in the data, ordered by count so the sidebar shows the bulk first.
 *
 * `allowed` narrows the numbers to the venues the other filters already keep, so the count
 * beside "Ballparks" is the number of ballparks the map would draw. Without it, picking
 * Wyoming left "18 of 6,884" sitting directly above "Other 2,105" — two counts of different
 * things, stacked, with nothing on screen saying so.
 *
 * The *order* is deliberately taken from the whole spine rather than from `allowed`: sorting
 * the filtered counts would rearrange eleven checkboxes every time the slider moved, under
 * the cursor of someone trying to tick one. Types that fall to zero stay listed for the same
 * reason, and because "Ballparks 0" is itself a useful answer.
 */
export function venueTypeCounts(
  fc: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties>,
  allowed?: Set<string>
): { type: string; count: number }[] {
  const total = new Map<string, number>();
  const counts = new Map<string, number>();
  for (const f of fc.features) {
    const p = f.properties;
    const t = p.venue_type || 'other';
    total.set(t, (total.get(t) ?? 0) + 1);
    if (!allowed || allowed.has(p.venue_id)) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  return [...total.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type]) => ({ type, count: counts.get(type) ?? 0 }));
}

/**
 * Words that make a fragment read as the name of a place rather than as a city, a team, an
 * honorific or a clause. Deliberately excludes near-misses that showed up in the data and
 * would have caused a bad split: `University` (would break "University of California, Los
 * Angeles Marshall Field"), `Recreation` ("Center for Athletics, Recreation & Wellness"),
 * `Golf` ("Paupack Hills Golf & Country Club, Golf Paupack") and `Casino` ("South Point
 * Hotel, Casino & Spa").
 */
const VENUE_WORD =
  /\b(stadiums?|arenas?|fields?|parks?|ballparks?|cent(?:er|re)s?|bowls?|complex(?:es)?|gymnasiums?|gyms?|colis(?:eum|seum)s?|domes?|auditoriums?|courses?|clubs?|theat(?:er|re)s?|pools?|rinks?|speedways?|raceways?|forums?|pavilions?|halls?|gardens?)\b/i;

const ALIAS_SEPARATOR = /[,;]|\s+\/\s+/;

/**
 * One alias field sometimes holds several names. OSM's `old_name` on Hard Rock Stadium is the
 * single string "Pro Player Stadium, Dolphin Stadium, Sun Life Stadium" — three former names
 * in one tag, which reads on screen as one absurd name.
 *
 * The commas cannot be trusted on their own. 137 aliases in the spine contain a comma and
 * only 8 of them are packed lists; the rest are "Name, Place" disambiguations ("Memorial
 * Stadium, Baltimore"), honorifics ("John A. Alario, Senior, Event Center") or names that
 * simply have a comma ("Pennsylvania Literary, Scientific, and Military Academy"). Splitting
 * on the comma alone fires on 113 of the 137 and invents a name for 105 venues — it would
 * put "Baltimore", "Texas" and "Scientific" on screen as former venue names.
 *
 * So every part has to independently look like a venue: 2-6 words, at least six characters,
 * and a venue word in it. Parenthesised strings are skipped outright, because those are
 * Wikipedia disambiguation titles ("Wells Fargo Arena (Dothan, Alabama)") where the comma is
 * always inside the parens. Measured over the whole spine this splits exactly the 8 real
 * lists and leaves the other 129 alone.
 *
 * Returns null when the string should be shown as-is, so callers can tell "leave it" apart
 * from "here are the parts".
 */
export function splitPackedName(raw: string): string[] | null {
  const s = raw.trim();
  if (s.includes('(') || s.includes(')')) return null;
  const parts = s.split(ALIAS_SEPARATOR).map((p) => p.trim());
  if (parts.length < 2) return null;
  for (const p of parts) {
    const words = p.split(/\s+/).length;
    if (p.length < 6 || words < 2 || words > 6 || !VENUE_WORD.test(p)) return null;
  }
  return parts;
}

/**
 * The undated aliases as they should be read, with packed lists broken out. The original
 * string is dropped once it has been split — it is not a name anyone used, it is a tag that
 * held three of them.
 */
export function displayNames(aliases: VenueAlias[]): string[] {
  const out: string[] = [];
  for (const a of aliases) {
    const parts = splitPackedName(a.name);
    if (parts) out.push(...parts);
    else out.push(a.name.trim());
  }
  return [...new Set(out)];
}

/** Name in use at a given year — what an article from that year would have printed. */
export function nameAtYear(venue: VenueProperties, y: number): string {
  const dated = venue.aliases.filter((a) => a.dated);
  for (const a of dated) {
    const start = year(a.start_date) ?? -9999;
    const end = year(a.end_date) ?? 9999;
    if (y >= start && y <= end) return a.name;
  }
  return venue.canonical_name;
}
