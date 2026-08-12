import {
  ACCENT_TEXT,
  BORDER,
  MUTED,
  MUTED_DIM,
  PANEL_OVER_MAP,
  WARN,
  WARN_SOFT,
} from '../theme';
import { dollars, percent, type AcsYear } from '../utils/acsTransform';
import { money, type FederalAward } from '../utils/federalTransform';
import {
  displayNames,
  nameAtYear,
  type VenueAlias,
  type VenueProperties,
} from '../utils/spineTransform';
import {
  CONTESTED_COLOR,
  holderIn,
  OTHER_OPERATOR_COLOR,
  type TenureProperties,
} from '../utils/tenureTransform';

interface VenuePanelProps {
  venue: VenueProperties;
  year: number;
  /** Every run on record at this venue, oldest first. */
  runs: TenureProperties[];
  /** Federal awards naming this venue, newest first. Almost always empty. */
  awards: FederalAward[];
  /** ACS context for the slider's own year, or null if that year was not published. */
  acs: AcsYear | null;
  /** The nearest published year, used only when `acs` is null and always labelled as such. */
  acsFallback: AcsYear | null;
  /** Why this venue has no context, when it has none. */
  acsNote: string | null;
  acsScopeNote: string | null;
  acsIncomeNote: string | null;
  /** The years ACS actually published, sorted. Passed rather than typed into the fallback
   *  sentence below: that sentence states the span as a fact, and a hand-written span is a
   *  claim about the payload that would keep reading true after the payload moved. */
  acsYears: number[];
  palette: Map<string, string>;
  onClose: () => void;
}

/** What the map is asserting for this venue in this year, in words. */
function holdersIn(runs: TenureProperties[], year: number): TenureProperties[] {
  return runs.filter(
    (r) =>
      r.start_year !== null &&
      r.render_end_year !== null &&
      r.start_year <= year &&
      r.render_end_year >= year
  );
}

const END_NOTE: Record<string, string> = {
  ended: 'end reported',
  ongoing: 'still held as of last coverage',
  unknown: 'evidence stops here; the end is unknown',
};

const EXIT_LABEL: Record<string, string> = {
  lost_bid: 'lost the bid',
  self_op_conversion: 'venue went self-operated',
  other: 'contract expired',
  unknown: 'cause not reported',
};

/**
 * Detail panel for one spine venue. The alias timeline is the reason this panel exists:
 * it is how you check, by eye, that "Enron Field" in a 2001 article and "Minute Maid Park"
 * in a 2015 article will resolve to the same venue_id during extraction.
 */
export function VenuePanel({
  venue,
  year,
  runs,
  awards,
  acs,
  acsFallback,
  acsNote,
  acsScopeNote,
  acsIncomeNote,
  acsYears,
  palette,
  onClose,
}: VenuePanelProps) {
  // Nested properties get serialized to strings when they round-trip through a GL
  // source, so the array may arrive as JSON text.
  const aliases: VenueAlias[] =
    typeof venue.aliases === 'string' ? JSON.parse(venue.aliases) : venue.aliases ?? [];
  const dated = aliases.filter((a) => a.dated);
  // Packed lists are broken out here, and the canonical name is dropped: it is nearly always
  // among the aliases, and listing it under "other known names" claims a second name that
  // does not exist.
  const undated = displayNames(aliases.filter((a) => !a.dated)).filter(
    (n) => n !== venue.canonical_name
  );
  const displayName = nameAtYear({ ...venue, aliases }, year);
  const holders = holdersIn(runs, year);
  // Resolved the same way the dot is, so the panel never names an operator the map is not
  // showing — including the handoff case, where two runs share a year but not a day.
  const holder = holders.length ? holderIn(holders) : null;
  const undatable = runs.filter((r) => r.start_year === null);
  // The slider's own year if ACS published one, otherwise the nearest year — which the
  // block below labels, so the two cases are never confusable on screen.
  const shown = acs ?? acsFallback;

  return (
    <div style={panelStyle}>
      <button onClick={onClose} style={closeStyle} aria-label="Close">
        ×
      </button>

      <h2 style={{ margin: '0 0 2px', fontSize: 16 }}>{displayName}</h2>
      {displayName !== venue.canonical_name && (
        <p style={{ ...mutedStyle, margin: '0 0 6px' }}>
          known today as {venue.canonical_name}
        </p>
      )}
      <p style={{ ...mutedStyle, margin: '0 0 14px' }}>
        {[venue.city, venue.state].filter(Boolean).join(', ') || 'Location unknown'} ·{' '}
        {venue.venue_type.replace(/_/g, ' ')}
      </p>

      <Row
        label={`Operator in ${year}`}
        value={
          holders.length === 0 ? (
            <span style={{ color: MUTED }}>
              {runs.length ? 'none on record' : 'no data yet'}
            </span>
          ) : holder ? (
            <span
              style={{
                color: palette.get(holder.operator_normalized ?? '') ?? OTHER_OPERATOR_COLOR,
              }}
            >
              {holder.operator_normalized}
            </span>
          ) : (
            <span style={{ color: CONTESTED_COLOR }} title="Both are reported; the pipeline flags this rather than choosing.">
              {holders.map((h) => h.operator_normalized).join(' + ')}
            </span>
          )
        }
      />
      <Row label="Opened" value={venue.opened_date ?? '—'} />
      <Row label="Closed" value={venue.closed_date ?? (venue.closed_year ? '—' : 'still open / unknown')} />
      <Row label="Capacity" value={venue.capacity ? venue.capacity.toLocaleString() : '—'} />
      <Row label="venue_id" value={<code style={codeStyle}>{venue.venue_id}</code>} />

      {runs.length > 0 && (
        <>
          <h3 style={h3Style}>Operator history</h3>
          <ul style={listStyle}>
            {runs.map((r) => {
              const held = holder ? r === holder : holders.includes(r);
              const color =
                palette.get(r.operator_normalized ?? '') ?? OTHER_OPERATOR_COLOR;
              return (
                <li key={r.tenure_id} style={runRowStyle}>
                  <div style={aliasRowStyle}>
                    <span style={{ color: held ? color : MUTED }}>
                      {r.operator_normalized}
                      {r.needs_review && <span style={flagStyle}> needs review</span>}
                    </span>
                    <span style={{ fontSize: 11, opacity: 0.85 }}>
                      {/* An unknown start is printed as "?" rather than guessed. It is also
                          why this run is not on the map: nothing can be placed on a timeline
                          without one end of it. */}
                      {r.start_year ?? '?'}–
                      {r.end_status === 'ended'
                        ? r.render_end_year ?? '?'
                        : r.end_status === 'ongoing'
                          ? 'now'
                          : `${r.render_end_year ?? '?'}?`}
                    </span>
                  </div>
                  <div style={{ ...mutedStyle, fontSize: 11 }}>
                    {END_NOTE[r.end_status ?? 'unknown']}
                    {r.end_status === 'ended' && r.exit_mode
                      ? ` · ${EXIT_LABEL[r.exit_mode] ?? r.exit_mode}`
                      : ''}
                    {r.end_inferred ? ' · inferred from the next operator' : ''}
                    {` · ${r.event_count} article${r.event_count === 1 ? '' : 's'}`}
                  </div>
                </li>
              );
            })}
          </ul>
          {undatable.length > 0 && (
            <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
              {undatable.length} run{undatable.length === 1 ? '' : 's'} above ha
              {undatable.length === 1 ? 's' : 've'} no start date, so {undatable.length === 1 ? 'it is' : 'they are'} never
              painted on the map — only listed here.
            </p>
          )}
        </>
      )}

      {awards.length > 0 && (
        <>
          <h3 style={h3Style}>Federal awards</h3>
          <ul style={listStyle}>
            {awards.map((a) => (
              <li key={a.award_id} style={runRowStyle}>
                <div style={aliasRowStyle}>
                  <span>{a.operator}</span>
                  <span style={{ fontSize: 11, opacity: 0.85 }}>
                    FY{a.fiscal_year ?? '?'} · {money(a.obligated_amount)}
                  </span>
                </div>
                <div style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.45 }}>
                  {a.awarding_sub_agency}
                  {/* The PIID is here so a claim on this panel can be looked up on
                      USAspending by someone who does not trust the join — which is the
                      right instinct, given the join rejected ten of its first twelve
                      matches as wrong. */}
                  {a.piid && <> · <code style={codeStyle}>{a.piid}</code></>}
                </div>
              </li>
            ))}
          </ul>
          {/* Read off `venue_match`, the join rule's own name, rather than restated by hand.
              The previous sentence here said the place check was against this venue's *city*.
              That stopped being true when the join moved to the place-of-performance ZIP, and
              the sentence went on confidently describing a rule the pipeline no longer ran —
              on the one panel whose whole job is to let a reader audit the match. Keying the
              text to the value means the next rule change either updates this or falls through
              to the honest default below. */}
          <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
            {MATCH_RULE[awards[0].venue_match] ??
              `Matched by the rule “${awards[0].venue_match}”, which this panel has no description for.`}{' '}
            Federal spending elsewhere is in the operator panel, not here.
          </p>
        </>
      )}

      {(acs || acsFallback || acsNote) && (
        <>
          <h3 style={h3Style}>Neighbourhood context</h3>
          {shown ? (
            <>
              <Row
                label="Median household income"
                value={dollars(shown.median_household_income)}
              />
              <Row label="Commute by transit" value={percent(shown.transit_share)} />
              <Row label="Commute 45 min or more" value={percent(shown.long_commute_share)} />
              <Row
                label="Workers"
                value={shown.workers_total?.toLocaleString() ?? '\u2014'}
              />
              <Row
                label="ZCTA"
                value={
                  <span>
                    <code style={codeStyle}>{shown.zcta}</code>
                    <span style={{ ...mutedStyle, marginLeft: 6 }}>
                      {shown.zcta_vintage} boundaries
                    </span>
                  </span>
                }
              />
              {/* Only ever shown when the slider's own year had nothing. Naming the year the
                  numbers actually come from is the difference between a useful fallback and
                  a quiet lie about what the slider is showing. */}
              {!acs && (
                <p style={warnStyle}>
                  {acsYears.length > 0 && (
                    <>
                      ACS 5-year estimates run {acsYears[0]}&ndash;
                      {acsYears[acsYears.length - 1]}.{' '}
                    </>
                  )}
                  These are {shown.year} figures, not {year}.
                </p>
              )}
              <p style={{ ...mutedStyle, fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
                {acsScopeNote}
              </p>
              <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
                {acsIncomeNote}
              </p>
            </>
          ) : (
            <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.5 }}>{acsNote}</p>
          )}
        </>
      )}

      {/* Always rendered, even when there is nothing in it. Hiding the heading made "no
          source states a date for this venue" look identical to "this venue never changed
          name", and the second is a claim the spine cannot make: only 78 of 6,884 venues
          have any dated name at all. */}
      <h3 style={h3Style}>Name history</h3>
      {dated.length > 0 ? (
        <ul style={listStyle}>
          {dated.map((a, i) => {
            const active =
              year >= Number(a.start_date?.slice(0, 4) ?? -9999) &&
              year <= Number(a.end_date?.slice(0, 4) ?? 9999);
            return (
              <li key={i} style={{ ...aliasRowStyle, color: active ? ACCENT_TEXT : MUTED }}>
                <span>{a.name}</span>
                <span style={{ fontSize: 11, opacity: 0.8 }}>
                  {a.start_date?.slice(0, 4) ?? '?'}–{a.end_date?.slice(0, 4) ?? 'now'}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        // Worded as a statement about the sources, not about the venue. A venue can have
        // been renamed three times and still land here.
        <p style={{ ...mutedStyle, lineHeight: 1.5 }}>
          {undated.length > 0
            ? 'No source dates these names. The names below are known, the years they were in use are not.'
            : 'Neither Wikidata nor OpenStreetMap records a former name for this venue. That is a gap in the sources, not evidence the name never changed.'}
        </p>
      )}

      {undated.length > 0 && (
        <>
          <h3 style={h3Style}>Other known names</h3>
          <p style={{ ...mutedStyle, lineHeight: 1.5 }}>{undated.join(' · ')}</p>
          <p style={{ ...mutedStyle, fontSize: 11, marginTop: 4 }}>
            Undated — matchable, but cannot date an article on its own.
          </p>
        </>
      )}

      {venue.name_is_ambiguous && (
        <p style={warnStyle}>
          This name is shared with another venue in the spine. Extraction must use city and
          state context before assigning a venue_id.
        </p>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={rowStyle}>
      <span style={mutedStyle}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 16,
  right: 16,
  width: 310,
  maxHeight: 'calc(100vh - 160px)',
  overflowY: 'auto',
  padding: '18px 18px 22px',
  background: PANEL_OVER_MAP,
  border: `1px solid ${BORDER}`,
  borderRadius: 10,
  zIndex: 6,
  fontSize: 13,
  backdropFilter: 'blur(6px)',
};

const closeStyle: React.CSSProperties = {
  position: 'absolute',
  top: 8,
  right: 10,
  background: 'none',
  border: 'none',
  color: MUTED,
  fontSize: 20,
  cursor: 'pointer',
  lineHeight: 1,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  padding: '4px 0',
  borderBottom: `1px solid ${BORDER}`,
};

const aliasRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 10,
  padding: '3px 0',
};

const h3Style: React.CSSProperties = {
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: MUTED_DIM,
  margin: '16px 0 6px',
};

/** `venue_match` -> what that rule actually checked. Keys must match `FEDERAL_VENUE_MATCH`
 *  in pipeline/schema.py; anything unlisted renders as a named-but-undescribed rule rather
 *  than as silence or as a stale explanation of a different rule. */
const MATCH_RULE: Record<string, string> = {
  name_and_zip:
    'Matched because the award names this venue, its place-of-performance ZIP falls inside ' +
    'the venue’s ZIP code area, and the name it matched on is one this venue actually ' +
    'records — not a fragment the spine generated.',
};

const listStyle: React.CSSProperties = { listStyle: 'none', margin: 0, padding: 0 };
const runRowStyle: React.CSSProperties = {
  padding: '5px 0',
  borderBottom: `1px solid ${BORDER}`,
};
const flagStyle: React.CSSProperties = { color: WARN, fontSize: 10, marginLeft: 6 };
const mutedStyle: React.CSSProperties = { color: MUTED, fontSize: 12 };
const codeStyle: React.CSSProperties = { fontSize: 11, color: MUTED };
const warnStyle: React.CSSProperties = {
  marginTop: 14,
  padding: '8px 10px',
  background: WARN_SOFT,
  border: `1px solid ${WARN}`,
  borderRadius: 6,
  color: WARN,
  fontSize: 11,
  lineHeight: 1.5,
};
