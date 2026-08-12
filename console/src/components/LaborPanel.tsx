import {
  ACCENT,
  ACCENT_SOFT,
  ACCENT_TEXT,
  BORDER,
  MUTED,
  MUTED_DIM,
  PANEL_OVER_MAP,
} from '../theme';
import {
  dollars,
  operatorsByBackWages,
  rejectionRate,
  sourceHost,
  yearSpan,
  type LaborProfile,
} from '../utils/laborTransform';

interface LaborPanelProps {
  profile: LaborProfile | null;
  onClose: () => void;
}

/**
 * Wage and hour enforcement by operator, in a panel because it has nowhere else to go.
 *
 * The panel leads with the rejection ratio rather than the dollar total, because the ratio is
 * what makes the dollar total trustworthy. Every figure below survived a name match that
 * threw away more rows than it kept, and the reader has no way to know that unless it is on
 * screen. The example in the rejection sentence is read out of the data, not typed here.
 */
export function LaborPanel({ profile, onClose }: LaborPanelProps) {
  if (!profile) return null;

  const ops = operatorsByBackWages(profile);
  const otherLine = profile.scope_counts.excluded_other_line ?? 0;
  const worstFalsePositive = profile.rejected_names_top.find((r) => r.legal_name.trim());
  const topExcluded = profile.excluded_other_line_top[0];
  const span = yearSpan(ops);
  const repeatCases = ops.reduce((s, o) => s + o.repeat_violator_cases, 0);

  return (
    <div style={panelStyle}>
      <button onClick={onClose} style={closeStyle} aria-label="Close">
        ×
      </button>

      <h2 style={{ margin: '0 0 2px', fontSize: 15 }}>Wage &amp; hour enforcement</h2>
      <p style={{ ...mutedStyle, margin: '0 0 14px', lineHeight: 1.5 }}>
        Concluded US Department of Labor Wage &amp; Hour Division cases against these
        operators{span && `, ${span}`}.
      </p>

      <div style={statRowStyle}>
        <Stat
          value={dollars(profile.back_wages_total)}
          label={`back wages · ${profile.cases_in_scope} cases`}
        />
        <Stat
          value={profile.employees_total.toLocaleString()}
          label={`workers owed · ${dollars(profile.penalties_total)} in penalties`}
        />
      </div>

      {/* The honest half of the layer. 493 of 840 fetched rows are companies that only look
          like an operator by substring, and a panel reporting the survivors alone would let
          a reader assume the query was clean. The worst example is pulled from the data so
          the sentence cannot outlive the snapshot that made it true. */}
      <p style={noteStyle}>
        {profile.source.candidate_rows} rows matched an operator name loosely and{' '}
        {profile.cases_in_scope} survived — {Math.round(rejectionRate(profile) * 100)}% were
        rejected as other companies
        {worstFalsePositive &&
          `, led by ${worstFalsePositive.legal_name} at ${worstFalsePositive.cases} cases`}
        . Another {otherLine} are these operators in a different line of business
        {topExcluded && ` (mostly ${topExcluded.naics_description.toLowerCase()})`} rather than
        food service.
      </p>

      <h3 style={h3Style}>By operator</h3>
      <ul style={listStyle}>
        {ops.map((e) => (
          <li key={e.operator} style={rowStyle}>
            <span style={{ maxWidth: 150 }}>{e.operator}</span>
            <span style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
              <span style={{ ...mutedStyle, fontSize: 11 }}>
                {e.cases} case{e.cases === 1 ? '' : 's'}
              </span>
              <span style={{ minWidth: 62, textAlign: 'right' }}>{dollars(e.back_wages)}</span>
            </span>
          </li>
        ))}
      </ul>
      {repeatCases > 0 && (
        <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
          {repeatCases} of these cases carry WHD&rsquo;s repeat-violator flag.
        </p>
      )}

      {/* The layer's central claim, printed from the profile rather than retyped, so that if
          a venue join is ever added the sentence stops being true in the pipeline and in the
          panel at the same moment. */}
      <p style={warnStyle}>{profile.venue_join}</p>

      <p style={noteStyle}>
        Source: {sourceHost(profile)} — {profile.source.note}
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
