import { ACCENT, BORDER_STRONG, MUTED, TEXT, WARN } from '../theme';
import { BAND_COLORS, BANDS, type Band, type BandKey } from '../utils/venueFilter';

interface NeighbourhoodFilterProps {
  band: Band;
  onPickBand: (key: BandKey) => void;
  chosen: number[];
  onToggleBucket: (i: number) => void;
  counts: number[];
  unknownCount: number;
  year: number;
  /** ACS runs 2011-2024; outside that there is nothing to filter on and we say so. */
  inAcsRange: boolean;
}

/**
 * Filter the map by the neighbourhood around each venue.
 *
 * This is the console's densest real filter — 6,831 of 6,884 venues have ACS context — and it
 * is the one that answers questions a reader actually arrives with: where are the venues in
 * transit-dependent neighbourhoods, where are the ones surrounded by long commutes.
 *
 * Two honesty rules are carried in the markup rather than the data layer, because this is
 * where a reader could be misled:
 *
 * The **cut points are printed on the controls**. "10-30%" is a stated threshold, not a
 * quantile that would silently re-cut itself whenever the year moved.
 *
 * Venues with **no ACS value for the chosen year are counted and named**, not folded into the
 * non-matching pile. A thinned map with no explanation reads as a finding; "1,412 venues have
 * no ACS data for 1994" reads as what it is.
 */
export function NeighbourhoodFilter({
  band,
  onPickBand,
  chosen,
  onToggleBucket,
  counts,
  unknownCount,
  year,
  inAcsRange,
}: NeighbourhoodFilterProps) {
  return (
    <>
      <label style={labelStyle} htmlFor="band-select">
        Measure
      </label>
      <select
        id="band-select"
        value={band.key}
        onChange={(e) => onPickBand(e.target.value as BandKey)}
        style={selectStyle}
      >
        {BANDS.map((b) => (
          <option key={b.key} value={b.key}>
            {b.label}
          </option>
        ))}
      </select>

      <p style={questionStyle}>{band.question}</p>

      {!inAcsRange && (
        <p style={warnStyle}>
          ACS runs 2011–2024. At {year} there is no neighbourhood data, so this filter is off
          and every venue stays on the map.
        </p>
      )}

      {inAcsRange && (
        <>
          <div role="group" aria-label={band.label}>
            {band.bucketLabels.map((lbl, i) => {
              const on = chosen.includes(i);
              return (
                <label key={lbl} style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => onToggleBucket(i)}
                    style={{ accentColor: ACCENT, width: 15, height: 15 }}
                  />
                  {/* The swatch is the only thing tying a dot on the map to a row here, so it
                      is drawn whether or not the row is ticked — a key that appears only after
                      you have already guessed what the colors mean is not a key. */}
                  <span
                    aria-hidden="true"
                    style={{ ...swatchStyle, background: BAND_COLORS[i] }}
                  />
                  <span style={{ flex: 1, color: TEXT }}>{lbl}</span>
                  <span style={{ color: MUTED, fontVariantNumeric: 'tabular-nums' }}>
                    {counts[i]?.toLocaleString() ?? 0}
                  </span>
                </label>
              );
            })}
          </div>

          <p style={noteStyle}>
            {chosen.length === 0
              ? 'Nothing selected — no filter applied, all venues shown in grey.'
              : `Showing ${chosen.length} of ${band.bucketLabels.length} bands, colored on the map.`}
          </p>

          {unknownCount > 0 && (
            <p style={noteStyle}>
              <strong style={{ color: WARN }}>{unknownCount.toLocaleString()}</strong> venues
              have no ACS value for {year} and are left on the map rather than hidden.
            </p>
          )}
        </>
      )}
    </>
  );
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: MUTED,
  marginBottom: 5,
};

const selectStyle: React.CSSProperties = {
  width: '100%',
  padding: '7px 9px',
  fontSize: 13,
  fontFamily: 'inherit',
  color: TEXT,
  background: '#ffffff',
  border: `1px solid ${BORDER_STRONG}`,
  borderRadius: 5,
};

const questionStyle: React.CSSProperties = {
  margin: '9px 0 10px',
  fontSize: 12,
  lineHeight: 1.5,
  color: MUTED,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 9,
  padding: '5px 0',
  fontSize: 13,
  cursor: 'pointer',
};

// Round rather than square, because it stands for a dot on the map and a square swatch beside
// a circular mark is a small lie about what the reader is looking for.
const swatchStyle: React.CSSProperties = {
  width: 11,
  height: 11,
  borderRadius: '50%',
  flexShrink: 0,
};

const noteStyle: React.CSSProperties = {
  margin: '8px 0 0',
  fontSize: 11,
  lineHeight: 1.5,
  color: MUTED,
};

const warnStyle: React.CSSProperties = {
  ...noteStyle,
  color: WARN,
};
