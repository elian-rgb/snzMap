import { CATEGORY_LABELS, LAYER_REGISTRY } from '../layerRegistry';
import {
  ACCENT,
  ACCENT_SOFT,
  ACCENT_TEXT,
  BORDER,
  ERROR,
  MUTED,
  MUTED_DIM,
  PANEL,
  SURFACE,
  TEXT,
  TEXT_HEADING,
  WARN,
} from '../theme';
import { listNames, money, type FederalProfile } from '../utils/federalTransform';
import {
  dollars,
  operatorsByBackWages,
  yearSpan,
  type LaborProfile,
} from '../utils/laborTransform';
import type { VenueProperties } from '../utils/spineTransform';
import type { StateCount } from '../utils/stateFilter';
import { NO_DATA_COLOR, type LegendEntry } from '../utils/tenureTransform';
import type { VenueHit } from '../utils/venueSearch';
import {
  METRICS,
  NO_VALUE_COLOR,
  type Choropleth,
  type MetricKey,
} from '../utils/zctaChoropleth';
import { NeighbourhoodFilter } from './NeighbourhoodFilter';
import { OperatorLens } from './OperatorLens';
import { Section } from './Section';
import { VenueSearch } from './VenueSearch';
import type { OperatorRow } from '../utils/operatorLens';
import type { Band, BandKey } from '../utils/venueFilter';

interface SidebarProps {
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null;
  onPickVenue: (hit: VenueHit) => void;
  typeCounts: { type: string; count: number }[];
  hiddenTypes: string[];
  onToggleType: (type: string) => void;
  totalVenues: number;
  visibleVenues: number;
  year: number;
  loading: boolean;
  error: string | null;
  /** Who holds how many venues in `year` — a readout, not a static key. */
  legend: LegendEntry[];
  coveredVenues: number;
  /** Total runs in the tenure file, so "no coverage" and "no file" read differently. */
  tenureRuns: number;
  tenureError: string | null;
  federalProfile: FederalProfile | null;
  /** Awards that name a spine venue. Small on purpose — see federalTransform. */
  federalVenueAwards: number;
  /** Dollars behind those awards, and the venues they land on. The headline figure. */
  federalVenueObligated: number;
  federalVenueCount: number;
  federalVenueNames: string[];
  onShowFederal: () => void;
  laborProfile: LaborProfile | null;
  onShowLabor: () => void;
  showZcta: boolean;
  onToggleZcta: () => void;
  zctaLoading: boolean;
  zctaError: string | null;
  /** Five bins for `year` and the chosen measure — see zctaChoropleth. */
  choropleth: Choropleth;
  zctaMetric: MetricKey;
  onPickZctaMetric: (m: MetricKey) => void;
  zctaScopeNote: string | null;
  /** States present among the currently drawn venues, with counts. */
  stateCounts: StateCount[];
  selectedState: string | null;
  onPickState: (state: string | null) => void;
  /** Venues carrying no state at all — 1,085 of 6,884, and named rather than hidden. */
  venuesWithoutState: number;
  /** Per-operator merge of federal + wage & hour + venue awards. */
  operatorRows: OperatorRow[];
  selectedOperator: string | null;
  onPickOperator: (operator: string | null) => void;
  /** The ACS band filter — the console's only filter backed by dense data. */
  band: Band;
  onPickBand: (key: BandKey) => void;
  chosenBuckets: number[];
  onToggleBucket: (i: number) => void;
  bandCounts: number[];
  bandUnknown: number;
  inAcsRange: boolean;
}

const TYPE_LABELS: Record<string, string> = {
  stadium: 'Stadiums',
  arena: 'Arenas',
  ballpark: 'Ballparks',
  convention_center: 'Convention centers',
  racetrack: 'Racetracks',
  amphitheater: 'Amphitheaters',
  golf_course: 'Golf courses',
  aquatic_center: 'Aquatic centers',
  ski_resort: 'Ski resorts',
  recreation: 'Recreation / gyms',
  other: 'Other',
};

export function Sidebar({
  spine,
  onPickVenue,
  typeCounts,
  hiddenTypes,
  onToggleType,
  totalVenues,
  visibleVenues,
  year,
  loading,
  error,
  legend,
  coveredVenues,
  tenureRuns,
  tenureError,
  federalProfile,
  federalVenueAwards,
  federalVenueObligated,
  federalVenueCount,
  federalVenueNames,
  onShowFederal,
  laborProfile,
  onShowLabor,
  showZcta,
  onToggleZcta,
  zctaLoading,
  zctaError,
  choropleth,
  zctaMetric,
  onPickZctaMetric,
  zctaScopeNote,
  stateCounts,
  selectedState,
  onPickState,
  venuesWithoutState,
  operatorRows,
  selectedOperator,
  onPickOperator,
  band,
  onPickBand,
  chosenBuckets,
  onToggleBucket,
  bandCounts,
  bandUnknown,
  inAcsRange,
}: SidebarProps) {
  const plannedLayers = LAYER_REGISTRY.filter((l) => l.status === 'planned');

  return (
    <aside style={asideStyle}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={titleStyle}>SNZ Console</h1>
        <p style={subtitleStyle}>Institutional food service, by place and time</p>
      </header>

      <VenueSearch spine={spine} year={year} onPick={onPickVenue} />

      <Section title="Venue spine" summary={`${visibleVenues.toLocaleString()} in ${year}`}>
        {loading && <p style={mutedStyle}>Loading venues…</p>}
        {error && <p style={errorStyle}>{error}</p>}
        {!loading && !error && (
          <>
            <p style={statStyle}>
              <strong style={{ fontSize: 22 }}>{visibleVenues.toLocaleString()}</strong>{' '}
              <span style={mutedStyle}>of {totalVenues.toLocaleString()} in {year}</span>
            </p>

            {/* Placed above the type checkboxes because it is the coarser cut: a reader who
                wants Texas arenas picks Texas first and then narrows. The option labels carry
                counts so the dropdown answers "is there anything there" before it is used. */}
            <label style={fieldLabelStyle} htmlFor="state-filter">
              State
            </label>
            <select
              id="state-filter"
              value={selectedState ?? ''}
              onChange={(e) => onPickState(e.target.value || null)}
              style={selectStyle}
            >
              <option value="">All states ({visibleVenues.toLocaleString()})</option>
              {stateCounts.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name} ({s.count.toLocaleString()})
                </option>
              ))}
            </select>
            {selectedState && venuesWithoutState > 0 && (
              // Said out loud, because filtering to a state silently drops these and a
              // reader has no way to tell an empty state from an unlabelled venue.
              <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.5, margin: '6px 0 10px' }}>
                {venuesWithoutState.toLocaleString()} venues carry no state in the spine and
                are hidden while a state is selected. They are unlabelled, not elsewhere.
              </p>
            )}
            {!selectedState && <div style={{ height: 10 }} />}
            <p style={{ ...mutedStyle, lineHeight: 1.5, marginBottom: 12 }}>
              {/* "Every dot is gray" stops being true the moment a neighbourhood band is
                  ticked, and a sentence that describes a map the reader is not looking at is
                  worse than no sentence. Grey still means the same thing in both states —
                  no operator on record — so the claim is narrowed rather than dropped. */}
              {chosenBuckets.length > 0 && inAcsRange
                ? `No dot is colored by operator: no tenure data exists yet, so the colors below are the ${band.label.toLowerCase()} band around each venue. Every venue here is still a documented gap on the operator question.`
                : tenureRuns === 0
                  ? 'Every dot is gray because no tenure data exists yet. Each one is a documented gap, not an absence of history.'
                  : `${(visibleVenues - coveredVenues).toLocaleString()} are gray: in the spine, no operator on record in ${year}. That is a documented gap, not an absence of history.`}
            </p>
            <ul style={listStyle}>
              {typeCounts.map(({ type, count }) => {
                const hidden = hiddenTypes.includes(type);
                return (
                  <li key={type}>
                    <label style={{ ...rowStyle, opacity: hidden ? 0.45 : 1 }}>
                      <input
                        type="checkbox"
                        checked={!hidden}
                        onChange={() => onToggleType(type)}
                        style={{ accentColor: ACCENT }}
                      />
                      <span style={{ flex: 1 }}>{TYPE_LABELS[type] ?? type}</span>
                      <span style={mutedStyle}>{count.toLocaleString()}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </Section>

      {/* Directly under the spine because "which company" is the question this console is
          named for, and it was previously answerable only by opening two separate panels and
          joining them by eye. */}
      <Section
        title="By company"
        summary={selectedOperator ?? `${operatorRows.length} operators`}
      >
        <OperatorLens
          rows={operatorRows}
          selected={selectedOperator}
          onSelect={onPickOperator}
          totalVenues={totalVenues}
          onShowFederal={onShowFederal}
          onShowLabor={onShowLabor}
        />
      </Section>

      <Section
        title="By neighbourhood"
        summary={
          chosenBuckets.length === 0
            ? 'no filter'
            : `${band.label}, ${chosenBuckets.length} band${chosenBuckets.length === 1 ? '' : 's'}`
        }
      >
        <NeighbourhoodFilter
          band={band}
          onPickBand={onPickBand}
          chosen={chosenBuckets}
          onToggleBucket={onToggleBucket}
          counts={bandCounts}
          unknownCount={bandUnknown}
          year={year}
          inAcsRange={inAcsRange}
        />
      </Section>

      <Section
        title={`Operators in ${year}`}
        summary={
          tenureRuns === 0 ? 'none on record' : `${coveredVenues.toLocaleString()} covered`
        }
      >
        {tenureError && <p style={errorStyle}>{tenureError}</p>}
        {!tenureError && tenureRuns === 0 && (
          <p style={{ ...mutedStyle, lineHeight: 1.5 }}>
            No runs on record. The pipeline emits this layer already; it stays empty until
            extracted events are paired into spans and emitted here.
          </p>
        )}
        {!tenureError && tenureRuns > 0 && (
          <>
            <p style={statStyle}>
              <strong style={{ fontSize: 22 }}>{coveredVenues.toLocaleString()}</strong>{' '}
              <span style={mutedStyle}>
                of {visibleVenues.toLocaleString()} venues have an operator
              </span>
            </p>
            <ul style={listStyle}>
              {legend.map(({ operator, color, venues }) => (
                <li key={operator} style={rowStyle}>
                  <span style={{ ...swatchStyle, background: color }} />
                  <span style={{ flex: 1 }}>{operator}</span>
                  <span style={mutedStyle}>{venues.toLocaleString()}</span>
                </li>
              ))}
              <li style={rowStyle}>
                <span style={{ ...swatchStyle, background: NO_DATA_COLOR }} />
                <span style={{ flex: 1, color: MUTED }}>No operator on record</span>
                <span style={mutedStyle}>
                  {(visibleVenues - coveredVenues).toLocaleString()}
                </span>
              </li>
            </ul>
            <p style={{ ...mutedStyle, fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
              A run is painted only between its start and the last year evidence supports.
              An operator whose coverage stops in 1998 stops being drawn in 1998.
            </p>
          </>
        )}
      </Section>

      {federalProfile && (
        <Section title="Federal awards" summary={money(federalVenueObligated)}>
          {/* The headline is the map-backed number, not the big one. $5.0B was here until it
              was measured against what the map can actually draw: $104,595 across 8 awards at
              three places, a factor of 48,000. As the 22px figure it read as "federal money
              flowing through these venues", which is a claim this data cannot support. The
              large total is still shown — it is real and it is the interesting finding — but
              it is now labelled with the universe it belongs to and sized as context. */}
          <p style={statStyle}>
            <strong style={{ fontSize: 22 }}>{money(federalVenueObligated)}</strong>{' '}
            <span style={mutedStyle}>
              at {federalVenueCount === 1 ? '1 venue' : `${federalVenueCount} venues`} on this
              map
            </span>
          </p>
          <p style={{ ...mutedStyle, lineHeight: 1.5, marginBottom: 10 }}>
            {federalVenueAwards} award{federalVenueAwards === 1 ? '' : 's'} in the spine, at{' '}
            {listNames(federalVenueNames)}.
          </p>
          <div style={contrastRowStyle}>
            <span style={{ flex: 1, color: TEXT_HEADING }}>
              All federal food service by these operators
            </span>
            <strong style={{ color: TEXT }}>
              {money(federalProfile.obligated_total)}
            </strong>
          </div>
          <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.5, marginBottom: 10 }}>
            {federalProfile.awards.toLocaleString()} awards, performed at military posts,
            federal buildings and VA hospitals — real spending, but not places this map
            contains. It is not venue concession revenue.
          </p>
          <p style={ringNoteStyle}>
            <span style={ringSwatchStyle} />
            Ringed on the map — the ring marks the venue, not the award.
          </p>
          <button onClick={onShowFederal} style={buttonStyle}>
            Spending by operator →
          </button>
        </Section>
      )}

      {laborProfile && (
        <Section title="Wage & hour" summary={dollars(laborProfile.back_wages_total)}>
          {/* No ring note here, and that absence is the point. Every other money section in
              this sidebar can point at something drawn on the map; this one cannot, because
              WHD records an employer address and never a venue. The section says so in its
              own words rather than leaving the reader to wonder which dots lit up. */}
          {/* The headline is qualified in the same breath as it is given. $2.1M read alone
              invites "these companies were fined $2.1M for what they do at these venues",
              and neither half of that is true: it is back pay, not a fine, and it is the
              operator anywhere in the country, not the venue. */}
          <p style={statStyle}>
            <strong style={{ fontSize: 22 }}>{dollars(laborProfile.back_wages_total)}</strong>{' '}
            <span style={mutedStyle}>in back wages, these operators anywhere</span>
          </p>
          <p style={{ ...mutedStyle, lineHeight: 1.5, marginBottom: 10 }}>
            {laborProfile.cases_in_scope} concluded Department of Labor cases against these
            operators{(() => {
              const span = yearSpan(laborProfile.by_operator);
              return span ? `, ${span}` : '';
            })()}
            , owing {laborProfile.employees_total.toLocaleString()} workers back pay.
          </p>
          {(() => {
            // Named from the data. Writing "led by Sodexo" here would be a claim that stops
            // being true the first time the snapshot is refreshed, and nothing would notice.
            const top = operatorsByBackWages(laborProfile)[0];
            if (!top) return null;
            return (
              <div style={contrastRowStyle}>
                <span style={{ flex: 1, color: TEXT_HEADING }}>
                  Largest, {top.operator}
                </span>
                <strong style={{ color: TEXT }}>{dollars(top.back_wages)}</strong>
              </div>
            );
          })()}
          <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.5, marginBottom: 10 }}>
            Not drawn on the map — {laborProfile.venue_join.charAt(0).toLowerCase()}
            {laborProfile.venue_join.slice(1)}
          </p>
          <button onClick={onShowLabor} style={buttonStyle}>
            Enforcement by operator →
          </button>
        </Section>
      )}

      <Section
        title="Neighbourhood context"
        summary={showZcta ? choropleth.metric.label : 'off'}
      >
        <label style={{ ...rowStyle, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={showZcta}
            onChange={onToggleZcta}
            style={{ accentColor: ACCENT }}
          />
          <span style={{ flex: 1 }}>Shade the ZIP area around each venue</span>
        </label>

        {showZcta && (
          // Switching measure re-bins geometry already in memory, so this is not gated on the
          // load finishing — but it is hidden when the layer is off, where it would offer a
          // choice with no visible consequence.
          <select
            value={zctaMetric}
            onChange={(e) => onPickZctaMetric(e.target.value as MetricKey)}
            style={selectStyle}
            aria-label="Measure to shade by"
          >
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        )}

        {zctaLoading && <p style={mutedStyle}>{'Loading boundaries\u2026 (~11 MB)'}</p>}
        {zctaError && <p style={errorStyle}>{zctaError}</p>}

        {/* The uncovered case, which is most of the slider: ACS runs 2011-2024 and the slider
            runs 1850-2026, so at 1990 every polygon in the vintage on screen — 3,885 of them
            on 2010 boundaries — is painted in the no-estimate color, because `matchColors`
            falls back to a flat fill when the color map is empty rather than drawing nothing.
            Until this existed the legend simply vanished with the bins and
            left a uniform tan wash over the country with nothing on screen to explain it —
            the same silence that would be read as "this neighbourhood measured low". The
            span is read out of the ACS payload rather than typed, so extending the pipeline's
            year range cannot leave this sentence behind. */}
        {showZcta &&
          !zctaLoading &&
          !zctaError &&
          choropleth.bins.length === 0 &&
          choropleth.years.length > 0 && (
            <div style={{ ...rowStyle, marginTop: 8, alignItems: 'flex-start' }}>
              <span
                style={{ ...swatchStyle, borderRadius: 2, background: NO_VALUE_COLOR }}
              />
              <span style={{ ...mutedStyle, flex: 1, fontSize: 11, lineHeight: 1.5 }}>
                Nothing is shaded in {year}. ACS published these estimates for{' '}
                {choropleth.years[0]}&ndash;{choropleth.years[choropleth.years.length - 1]}{' '}
                only, so every ZIP area on screen is drawn in the no-estimate color. Move the
                slider into that span to shade them.
              </span>
            </div>
          )}

        {showZcta && !zctaLoading && !zctaError && choropleth.bins.length > 0 && (
          <>
            {/* The cutoffs are always printed, because for a `rank` measure they move every
                year and a legend that hid that would be claiming a stability the numbers do
                not have. For a `fixed` measure they stay put and the counts move instead. */}
            <ul style={{ ...listStyle, marginTop: 8 }}>
              {choropleth.bins.map((bin, i) => (
                <li key={bin.color} style={rowStyle}>
                  <span style={{ ...swatchStyle, borderRadius: 2, background: bin.color }} />
                  <span style={{ flex: 1 }}>
                    {choropleth.metric.format(bin.min)}
                    {i === choropleth.bins.length - 1
                      ? '+'
                      : `\u2013${choropleth.metric.format(bin.max)}`}
                  </span>
                  <span style={mutedStyle}>{bin.zctas.toLocaleString()}</span>
                </li>
              ))}
              {choropleth.withoutValue > 0 && (
                <li style={rowStyle}>
                  <span
                    style={{ ...swatchStyle, borderRadius: 2, background: NO_VALUE_COLOR }}
                  />
                  <span style={{ flex: 1, color: MUTED }}>No estimate in {year}</span>
                  <span style={mutedStyle}>
                    {choropleth.withoutValue.toLocaleString()}
                  </span>
                </li>
              )}
            </ul>
            <p style={{ ...mutedStyle, fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
              {choropleth.metric.scale === 'rank'
                ? `Fifths of the venue neighbourhoods drawn in ${year}, on ${choropleth.vintage}-Census ZIP areas.`
                : `Fifths of every year pooled, on ${choropleth.vintage}-Census ZIP areas. The counts are ${year}.`}{' '}
              {choropleth.metric.note}
            </p>
            {zctaScopeNote && (
              <p style={{ ...mutedStyle, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
                {zctaScopeNote}
              </p>
            )}
          </>
        )}
      </Section>

      {/* What used to be here was the full 18-row layer registry, 12 of them `planned`. It was
          a roadmap sitting in a navigation column: nothing in it could be clicked, and reading
          it top to bottom told you mostly what does not exist. It is gone from the sidebar.

          This one line replaces it, and it is not decoration. The distinction between "this
          data does not exist" and "nobody attempted this" is the one the whole project is
          built to keep visible, and a console that silently showed only its finished layers
          would be claiming completeness it does not have. The count is derived from the
          registry rather than typed, so it cannot drift when a layer lands. */}
      <details style={notBuiltStyle}>
        <summary style={notBuiltSummaryStyle}>
          {plannedLayers.length} more layers are planned but not built
        </summary>
        <p style={{ ...mutedStyle, fontSize: 11, lineHeight: 1.5, margin: '8px 0 6px' }}>
          Listed so the gap is visible rather than looking like something nobody got to. None
          of these carry data today.
        </p>
        <ul style={{ ...listStyle, margin: 0 }}>
          {plannedLayers.map((layer) => (
            <li
              key={layer.key}
              title={`${layer.description}\n\nSource: ${layer.source}`}
              style={{ ...rowStyle, cursor: 'help', fontSize: 12 }}
            >
              <span
                style={{ width: 6, height: 6, borderRadius: 99, background: MUTED_DIM }}
              />
              <span style={{ flex: 1, color: MUTED }}>{layer.label}</span>
              <span style={{ ...mutedStyle, fontSize: 11 }}>
                {CATEGORY_LABELS[layer.category]}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </aside>
  );
}

// Boxed rather than run into the paragraph above it, so the two dollar figures are visibly
// answers to two different questions instead of two numbers in the same breath.
const contrastRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 10,
  padding: '7px 9px',
  marginBottom: 6,
  background: PANEL,
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  fontSize: 12,
};

const ringNoteStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  color: TEXT_HEADING,
  fontSize: 12,
  marginBottom: 10,
};

// Hollow on purpose: it is the same shape the map draws, so the legend and the map are
// recognizably the same mark rather than two things a reader has to connect.
const ringSwatchStyle: React.CSSProperties = {
  width: 11,
  height: 11,
  borderRadius: 99,
  border: `1.6px solid ${WARN}`,
  flexShrink: 0,
};

const asideStyle: React.CSSProperties = {
  padding: '22px 18px',
  borderRight: `1px solid ${BORDER}`,
  overflowY: 'auto',
  background: SURFACE,
  fontSize: 13,
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 19,
  letterSpacing: '-0.01em',
};

const subtitleStyle: React.CSSProperties = {
  margin: '4px 0 0',
  fontSize: 12,
  color: MUTED,
};

const listStyle: React.CSSProperties = { listStyle: 'none', margin: 0, padding: 0 };

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '4px 0',
};

const swatchStyle: React.CSSProperties = {
  width: 9,
  height: 9,
  borderRadius: 99,
  flexShrink: 0,
};

const mutedStyle: React.CSSProperties = { color: MUTED, fontSize: 12 };
const statStyle: React.CSSProperties = { margin: '0 0 6px' };

// The dropdown's own label. Uppercase and small like the section headings, one step in from
// them, so the filter reads as part of the section rather than as a new section.
const fieldLabelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: MUTED_DIM,
  marginTop: 4,
};

const buttonStyle: React.CSSProperties = {
  width: '100%',
  padding: '7px 10px',
  background: ACCENT_SOFT,
  border: `1px solid ${ACCENT}`,
  borderRadius: 6,
  color: ACCENT_TEXT,
  fontSize: 12,
  cursor: 'pointer',
  textAlign: 'left',
};
const selectStyle: React.CSSProperties = {
  width: '100%',
  marginTop: 8,
  padding: '6px 8px',
  background: PANEL,
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  color: TEXT,
  fontSize: 12,
  cursor: 'pointer',
};
const errorStyle: React.CSSProperties = { color: ERROR, fontSize: 12, lineHeight: 1.5 };

const notBuiltStyle: React.CSSProperties = {
  marginTop: 4,
  paddingTop: 12,
  borderTop: `1px solid ${BORDER}`,
};

const notBuiltSummaryStyle: React.CSSProperties = {
  cursor: 'pointer',
  fontSize: 11,
  color: MUTED,
  listStyle: 'revert',
};
