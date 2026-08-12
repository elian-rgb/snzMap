import { ACCENT_TEXT, BORDER, MUTED, MUTED_DIM, PANEL_OVER_MAP } from '../theme';
import type { ZctaDetail } from '../utils/zctaChoropleth';

interface ZctaPanelProps {
  detail: ZctaDetail;
  /** Which measure the map is currently shaded by, so the panel can mark that row. */
  activeMetric: string;
  /** Names of the venues that put this ZCTA on the map, in spine order. */
  venueNames: string[];
  scopeNote: string | null;
  incomeNote: string | null;
  onClose: () => void;
}

/**
 * Detail for one shaded area.
 *
 * The panel exists because the choropleth can only show one measure at a time, and a reader
 * who has just been told this neighbourhood is in the bottom fifth for transit will
 * reasonably want to know what else is true about it. All four measures are listed, not just
 * the one being shaded.
 *
 * It also carries the thing the color cannot: the ZCTA is not the venue. Naming the venues
 * inside it is the most direct way to make the relationship visible — this shape is on screen
 * *because* those buildings are in it, and its numbers describe the postal area around them,
 * not the buildings.
 */
export function ZctaPanel({
  detail,
  activeMetric,
  venueNames,
  scopeNote,
  incomeNote,
  onClose,
}: ZctaPanelProps) {
  // Nothing published at all this year, as distinct from one measure being missing.
  const empty = detail.values.every((v) => v.value === null);

  return (
    <div style={panelStyle}>
      <button onClick={onClose} style={closeStyle} aria-label="Close">
        ×
      </button>

      <h2 style={{ margin: '0 0 2px', fontSize: 16 }}>ZIP area {detail.zcta}</h2>
      <p style={{ ...mutedStyle, margin: '0 0 14px' }}>
        {detail.year} · {detail.vintage}-Census boundaries
      </p>

      {empty ? (
        <p style={{ ...mutedStyle, fontSize: 12, lineHeight: 1.5 }}>
          ACS published no estimates for this ZIP area in {detail.year}. It is drawn because a
          venue sits inside it, and shaded as &ldquo;no estimate&rdquo; rather than left out,
          so an absent figure cannot be mistaken for a low one.
        </p>
      ) : (
        <>
          {detail.values.map(({ metric, value }) => {
            const active = metric.key === activeMetric;
            return (
              <div key={metric.key} style={rowStyle}>
                <span style={{ ...mutedStyle, color: active ? ACCENT_TEXT : MUTED }}>
                  {metric.label}
                  {/* The shaded measure is marked, because a reader arriving from a color
                      needs to know which of these four rows that color was about. */}
                  {active && <span style={{ fontSize: 10 }}> · shaded</span>}
                </span>
                <span style={{ color: value === null ? MUTED : undefined }}>
                  {value === null ? 'no estimate' : metric.format(value)}
                </span>
              </div>
            );
          })}
        </>
      )}

      <h3 style={h3Style}>
        {venueNames.length === 1 ? 'The venue here' : `Venues here (${venueNames.length})`}
      </h3>
      <p style={{ ...mutedStyle, fontSize: 12, lineHeight: 1.5 }}>
        {venueNames.length ? venueNames.join(' · ') : 'None found in the spine.'}
      </p>
      <p style={{ ...mutedStyle, fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
        {scopeNote}
      </p>
      {/* Shown whenever income is on screen, whether or not it is the shaded measure — the
          nominal-dollar caveat applies to the number itself, not to how it is colored. */}
      {incomeNote && !empty && (
        <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
          {incomeNote}
        </p>
      )}
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

const h3Style: React.CSSProperties = {
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: MUTED_DIM,
  margin: '16px 0 6px',
};

const mutedStyle: React.CSSProperties = { color: MUTED, fontSize: 12 };
