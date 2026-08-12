import {
  ACCENT,
  ACCENT_SOFT,
  ACCENT_TEXT,
  BORDER,
  MUTED,
  MUTED_DIM,
  PANEL_OVER_MAP,
} from '../theme';
import { money, type FederalProfile } from '../utils/federalTransform';

interface FederalPanelProps {
  profile: FederalProfile | null;
  venueAwards: number;
  /** Dollars behind the venue-matched awards — four orders of magnitude below the profile. */
  venueObligated: number;
  onClose: () => void;
}

/**
 * Federal spending by operator, in a panel rather than on the map.
 *
 * The panel leads with the ratio — a few hundred of nearly ten thousand awards, a handful of
 * which name a spine venue — because that ratio is the finding. The exact figures are printed
 * from the profile, not from here. A reader who sees "$5.0B of federal food service"
 * without it will assume it describes stadium concessions, and it does not: it is very
 * largely Marine Corps mess halls.
 */
export function FederalPanel({
  profile,
  venueAwards,
  venueObligated,
  onClose,
}: FederalPanelProps) {
  if (!profile) return null;

  const top = profile.by_operator[0];
  const remoteSites = profile.scope_counts.remote_sites ?? 0;

  return (
    <div style={panelStyle}>
      <button onClick={onClose} style={closeStyle} aria-label="Close">
        ×
      </button>

      <h2 style={{ margin: '0 0 2px', fontSize: 15 }}>Federal food service</h2>
      <p style={{ ...mutedStyle, margin: '0 0 14px', lineHeight: 1.5 }}>
        USAspending prime contract awards to the four operators, {new Date().getFullYear()}{' '}
        download.
      </p>

      {/* Both totals, side by side and both labelled with their universe. Showing only the
          $5.0B and a count of 4 left the reader to assume the four awards were a meaningful
          slice of it; they are 0.002% of it. The dollar figure for the map is the only way
          to make that visible without arithmetic. */}
      <div style={statRowStyle}>
        <Stat value={money(venueObligated)} label={`on this map · ${venueAwards} awards`} />
        <Stat
          value={money(profile.obligated_total)}
          label={`these operators anywhere · ${profile.awards.toLocaleString()} awards`}
        />
      </div>
      <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.55, margin: '10px 0 0' }}>
        The left figure is what this map can evidence. The right is{' '}
        {Math.round(profile.obligated_total / Math.max(venueObligated, 1)).toLocaleString()}×
        larger and is a different universe — the same four companies feeding military posts
        and federal buildings.
      </p>

      {/* The rejection ratio, read out of the profile rather than typed. Every figure in this
          sentence used to be a literal, and one of them had already gone stale without
          anything on screen or in the tests noticing: the panel claimed the remote-site rows
          "would make Sodexo look roughly 400× the size of Aramark", which no reading of the
          current export reproduces (dollars give 160×, awards give 763×). A sentence that
          states the size of a rejection is a claim about the rejection, so it is derived. */}
      <p style={noteStyle}>
        {profile.rows_loaded.toLocaleString()} awards were read and {profile.awards} kept.
        The rest are work performed abroad, non–food service NAICS, or Sodexo&rsquo;s
        remote-site catering arm
        {remoteSites > 0 && (
          <>
            {' '}
            — {remoteSites.toLocaleString()} rows on its own,{' '}
            {Math.round((remoteSites / profile.rows_loaded) * 100)}% of everything read and{' '}
            {Math.round(remoteSites / profile.awards)}× the whole in-scope set. Folding those
            in would let one offshore-camp subsidiary outweigh every operator here purely as
            an artifact of how the export was filtered
          </>
        )}
        . Every excluded row is written to{' '}
        <code style={codeStyle}>federal_exclusions.csv</code> with the rule that stopped it.
      </p>

      <h3 style={h3Style}>By operator</h3>
      <ul style={listStyle}>
        {profile.by_operator.map((e) => (
          <li key={e.operator} style={rowStyle}>
            <span>{e.operator}</span>
            <span style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
              <span style={{ ...mutedStyle, fontSize: 11 }}>
                {e.awards} award{e.awards === 1 ? '' : 's'}
              </span>
              <span style={{ minWidth: 46, textAlign: 'right' }}>{money(e.obligated)}</span>
            </span>
          </li>
        ))}
      </ul>
      {top && (
        <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
          {top.operator} is {Math.round((top.obligated / profile.obligated_total) * 100)}% of
          the total, almost entirely Navy garrison mess hall contracts — not concessions.
        </p>
      )}

      <h3 style={h3Style}>By awarding agency</h3>
      <ul style={listStyle}>
        {profile.by_agency.slice(0, 8).map((e) => (
          <li key={e.agency} style={rowStyle}>
            <span style={{ maxWidth: 190 }}>{e.agency}</span>
            <span style={{ minWidth: 46, textAlign: 'right' }}>{money(e.obligated)}</span>
          </li>
        ))}
      </ul>

      <p style={warnStyle}>
        This is spending by an operator, not activity at a venue. It is kept off the map on
        purpose: these contracts are performed at military posts and federal buildings that
        a spine of stadiums and arenas does not contain.
      </p>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
      <div style={{ ...mutedStyle, fontSize: 10, lineHeight: 1.3 }}>{label}</div>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 16,
  left: 16,
  width: 320,
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

const statRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(2, 1fr)',
  gap: 14,
  padding: '10px 0 12px',
  borderTop: `1px solid ${BORDER}`,
  borderBottom: `1px solid ${BORDER}`,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  padding: '4px 0',
  borderBottom: `1px solid ${BORDER}`,
};

const h3Style: React.CSSProperties = {
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: MUTED_DIM,
  margin: '16px 0 6px',
};

const listStyle: React.CSSProperties = { listStyle: 'none', margin: 0, padding: 0 };
const mutedStyle: React.CSSProperties = { color: MUTED, fontSize: 12 };
const codeStyle: React.CSSProperties = { fontSize: 10, color: MUTED };
const noteStyle: React.CSSProperties = {
  ...mutedStyle,
  fontSize: 11,
  lineHeight: 1.55,
  margin: '12px 0 0',
};
const warnStyle: React.CSSProperties = {
  marginTop: 16,
  padding: '8px 10px',
  background: ACCENT_SOFT,
  border: `1px solid ${ACCENT}`,
  borderRadius: 6,
  color: ACCENT_TEXT,
  fontSize: 11,
  lineHeight: 1.5,
};
