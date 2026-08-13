import {
  ACCENT,
  ACCENT_SOFT,
  ACCENT_TEXT,
  BORDER,
  BORDER_STRONG,
  MUTED,
  PANEL,
  SURFACE,
  TEXT,
  WARN,
  WARN_SOFT,
} from '../theme';
import type { OperatorRow } from '../utils/operatorLens';

interface OperatorLensProps {
  rows: OperatorRow[];
  selected: string | null;
  onSelect: (operator: string | null) => void;
  /** Total venues in the spine, so "how many do we know the operator of" is answerable. */
  totalVenues: number;
  onShowFederal: () => void;
  onShowLabor: () => void;
}

const money = (n: number) => {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${Math.round(n)}`;
};

/**
 * Pick a company, see what this console actually holds on it.
 *
 * The honest problem this component exists to present rather than hide: **no venue in the
 * spine carries an operator.** Establishing who held the contract where is the thing the
 * article pipeline is being built to do, and it has not produced that yet. So "filter the map
 * by company" cannot mean what a reader expects — there is nothing on 6,876 of 6,884 venues
 * to filter by.
 *
 * What does exist per operator is real and worth reading: federal contract spending, DOL wage
 * & hour enforcement, and a handful of federal awards that do name a spine venue. This shows
 * those, maps the handful that can be mapped, and states the gap in the same breath rather
 * than leaving the reader to infer it from an empty map.
 */
export function OperatorLens({
  rows,
  selected,
  onSelect,
  totalVenues,
  onShowFederal,
  onShowLabor,
}: OperatorLensProps) {
  const active = rows.find((r) => r.operator === selected) ?? null;

  return (
    <>
      <p style={introStyle}>
        Nine operators, from federal contracting and Department of Labor records. Pick one to
        see what is on record.
      </p>

      <div style={chipWrapStyle}>
        <button
          onClick={() => onSelect(null)}
          style={chipStyle(selected === null)}
          aria-pressed={selected === null}
        >
          All
        </button>
        {rows.map((r) => (
          <button
            key={r.operator}
            onClick={() => onSelect(r.operator === selected ? null : r.operator)}
            style={chipStyle(r.operator === selected)}
            aria-pressed={r.operator === selected}
          >
            {r.operator}
          </button>
        ))}
      </div>

      {!active && (
        <p style={noteStyle}>
          Selecting a company does not filter the venue map. No venue in the spine carries an
          operator yet — that is what the article pipeline is for.
        </p>
      )}

      {active && (
        <div style={{ marginTop: 12 }}>
          {/* Venue-level first. It is by far the smallest number here and by far the most
              relevant one, and putting the $B figure first would make everything after it
              read as a footnote to a number that is not about venues at all. */}
          <div style={active.venueAwards > 0 ? cardStyle : mutedCardStyle}>
            <div style={cardLabelStyle}>On this map</div>
            {active.venueAwards > 0 ? (
              <>
                <div style={bigStyle}>
                  {active.venueAwards} award{active.venueAwards === 1 ? '' : 's'}{' '}
                  <span style={{ fontSize: 13, fontWeight: 400, color: MUTED }}>
                    at {active.venueNames.length} venue
                    {active.venueNames.length === 1 ? '' : 's'}, {money(active.venueObligated)}
                  </span>
                </div>
                <div style={smallStyle}>{active.venueNames.join(', ')}</div>
                <div style={smallStyle}>Ringed on the map.</div>
              </>
            ) : (
              <div style={smallStyle}>
                No award in this spine names a venue for {active.operator}. Nothing to draw.
              </div>
            )}
          </div>

          <div style={gapStyle}>
            <strong style={{ color: WARN }}>
              0 of {totalVenues.toLocaleString()} venues
            </strong>{' '}
            have {active.operator} on record as the food-service operator. Contract history
            comes from the article pipeline, which has not been run over the full corpus.
          </div>

          <div style={rowStyle}>
            <span style={rowLabelStyle}>Federal food service, anywhere</span>
            <span style={rowValueStyle}>{money(active.obligated)}</span>
          </div>
          <div style={smallStyle}>
            {active.federalAwards.toLocaleString()} awards at military posts, federal buildings
            and VA hospitals. Real spending, but not places this map contains — it is not venue
            concession revenue.
          </div>
          <button onClick={onShowFederal} style={linkStyle}>
            Spending by operator →
          </button>

          <div style={{ ...rowStyle, marginTop: 14 }}>
            <span style={rowLabelStyle}>Wage &amp; hour back wages</span>
            <span style={rowValueStyle}>{money(active.backWages)}</span>
          </div>
          {active.cases > 0 ? (
            <div style={smallStyle}>
              {active.cases} concluded case{active.cases === 1 ? '' : 's'}
              {active.firstYear && active.lastYear
                ? `, ${active.firstYear}–${active.lastYear}`
                : ''}
              , owing {active.employees.toLocaleString()} workers back pay.
              {active.repeatCases > 0 && ` ${active.repeatCases} repeat-violator cases.`}
            </div>
          ) : (
            <div style={smallStyle}>No concluded cases on record for this operator.</div>
          )}
          <div style={smallStyle}>
            Not drawn on the map — WHISARD records an employer address, never a venue.
          </div>
          <button onClick={onShowLabor} style={linkStyle}>
            Enforcement by operator →
          </button>
        </div>
      )}
    </>
  );
}

const introStyle: React.CSSProperties = {
  margin: '0 0 10px',
  fontSize: 12,
  lineHeight: 1.5,
  color: MUTED,
};

const chipWrapStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
};

const chipStyle = (on: boolean): React.CSSProperties => ({
  padding: '5px 10px',
  fontSize: 12,
  borderRadius: 999,
  cursor: 'pointer',
  fontFamily: 'inherit',
  background: on ? ACCENT : SURFACE,
  color: on ? '#ffffff' : TEXT,
  // The ring is what carries selection; the fill only confirms it. Both are present so the
  // control does not depend on color alone.
  border: `1px solid ${on ? ACCENT : BORDER_STRONG}`,
  fontWeight: on ? 600 : 400,
});

const cardStyle: React.CSSProperties = {
  background: ACCENT_SOFT,
  border: `1px solid ${ACCENT}`,
  borderRadius: 6,
  padding: '10px 12px',
  marginBottom: 10,
};

const mutedCardStyle: React.CSSProperties = {
  ...cardStyle,
  background: PANEL,
  border: `1px solid ${BORDER}`,
};

const cardLabelStyle: React.CSSProperties = {
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: MUTED,
  marginBottom: 4,
};

const bigStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  color: TEXT,
  marginBottom: 4,
};

const gapStyle: React.CSSProperties = {
  background: WARN_SOFT,
  border: `1px solid ${WARN}`,
  borderRadius: 6,
  padding: '9px 11px',
  fontSize: 12,
  lineHeight: 1.5,
  color: TEXT,
  marginBottom: 14,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'baseline',
  gap: 10,
  marginTop: 4,
};

const rowLabelStyle: React.CSSProperties = { fontSize: 12, color: TEXT };
const rowValueStyle: React.CSSProperties = { fontSize: 16, fontWeight: 700, color: TEXT };

const smallStyle: React.CSSProperties = {
  fontSize: 11,
  lineHeight: 1.5,
  color: MUTED,
  marginTop: 3,
};

const noteStyle: React.CSSProperties = {
  ...smallStyle,
  marginTop: 10,
};

const linkStyle: React.CSSProperties = {
  marginTop: 6,
  padding: 0,
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: ACCENT_TEXT,
  fontSize: 12,
  fontFamily: 'inherit',
  textDecoration: 'underline',
};
