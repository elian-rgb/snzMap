import { useEffect, useMemo, useState } from 'react';
import Slider from 'rc-slider';
import 'rc-slider/assets/index.css';
import { FederalPanel } from './components/FederalPanel';
import { LaborPanel } from './components/LaborPanel';
import { MapErrorBoundary } from './components/MapErrorBoundary';
import { MapView } from './components/MapView';
import { Sidebar } from './components/Sidebar';
import { VenuePanel } from './components/VenuePanel';
import { LAYER_BY_KEY } from './layerRegistry';
import {
  ACCENT,
  BORDER,
  BORDER_STRONG,
  MUTED,
  PANEL_OVER_MAP,
  SURFACE,
  TEXT,
} from './theme';
import {
  contextForVenue,
  coverageNote,
  loadAcsContext,
  nearestYear,
  type AcsContext,
} from './utils/acsTransform';
import {
  awardsForVenue,
  loadFederalAwards,
  loadFederalProfile,
  venueAwardTotals,
  type FederalAward,
  type FederalProfile,
} from './utils/federalTransform';
import { loadLaborProfile, type LaborProfile } from './utils/laborTransform';
import {
  loadSpine,
  venueTypeCounts,
  type VenueProperties,
} from './utils/spineTransform';
import {
  loadTenure,
  operatorLegend,
  operatorPalette,
  runsForVenue,
  venueColorsAt,
  type TenureProperties,
} from './utils/tenureTransform';
import {
  boundsForState,
  stateCounts,
  venuesWithoutState,
} from './utils/stateFilter';
import type { VenueHit } from './utils/venueSearch';
import { ZctaPanel } from './components/ZctaPanel';
import {
  choroplethFor,
  loadZctaShapes,
  vintageForYear,
  zctaDetail,
  type MetricKey,
  type ZctaShapes,
} from './utils/zctaChoropleth';

// The article corpus is ~20 years; the spine runs earlier because defunct venues matter.
// 1850 rather than 1950 because 841 venues in the spine opened before 1950 and 65 had
// already closed by then — a 1950 floor made those unreachable, and search could set a year
// outside the slider's range, leaving the handle pinned at the floor while the readout
// showed a year the handle could not express. Roughly twenty venues predate 1850; they stay
// visible at the floor, since the filter is `opened_year <= year`.
const MIN_YEAR = 1850;
const MAX_YEAR = new Date().getFullYear();
const clampYear = (y: number) => Math.min(Math.max(y, MIN_YEAR), MAX_YEAR);

export default function App() {
  const [spine, setSpine] = useState<GeoJSON.FeatureCollection<
    GeoJSON.Point,
    VenueProperties
  > | null>(null);
  const [tenure, setTenure] = useState<TenureProperties[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tenureError, setTenureError] = useState<string | null>(null);
  const [year, setYear] = useState(2015);
  const [hiddenTypes, setHiddenTypes] = useState<string[]>([]);
  const [selected, setSelected] = useState<VenueProperties | null>(null);
  const [federal, setFederal] = useState<FederalAward[]>([]);
  const [federalProfile, setFederalProfile] = useState<FederalProfile | null>(null);
  const [showFederal, setShowFederal] = useState(false);
  const [laborProfile, setLaborProfile] = useState<LaborProfile | null>(null);
  const [showLabor, setShowLabor] = useState(false);
  const [acs, setAcs] = useState<AcsContext | null>(null);
  const [flyTo, setFlyTo] = useState<{ lng: number; lat: number; nonce: number } | null>(null);
  const [showZcta, setShowZcta] = useState(false);
  const [zcta, setZcta] = useState<ZctaShapes | null>(null);
  const [zctaLoading, setZctaLoading] = useState(false);
  const [zctaError, setZctaError] = useState<string | null>(null);
  // Income first because it is the most legible of the four, not because it is the most
  // important. Switching metric re-bins the existing geometry; it never refetches.
  const [zctaMetric, setZctaMetric] = useState<MetricKey>('median_household_income');
  const [selectedZcta, setSelectedZcta] = useState<string | null>(null);
  const [selectedState, setSelectedState] = useState<string | null>(null);
  const [fitBounds, setFitBounds] = useState<{
    bounds: [[number, number], [number, number]];
    nonce: number;
  } | null>(null);

  useEffect(() => {
    const src = LAYER_BY_KEY.venue_spine.src!;
    loadSpine(src)
      .then(setSpine)
      .catch((e: Error) => setError(e.message));
  }, []);

  // Loaded separately from the spine, and a failure here is reported separately too: the
  // spine is the map, tenure is what is known about it. Losing the second must not blank
  // the first.
  useEffect(() => {
    const src = LAYER_BY_KEY.contract_tenure.src!;
    loadTenure(src)
      .then(setTenure)
      .catch((e: Error) => setTenureError(e.message));
  }, []);

  // Federal is a third independent load. It is the only real contract data in the project,
  // and it must not be able to take the spine or the tenure layer down with it if the
  // pipeline has not emitted it — so its failure is swallowed to an empty layer, the same
  // bargain the registry makes by shipping layers as 'planned'.
  useEffect(() => {
    loadFederalAwards(LAYER_BY_KEY.money_federal.src!)
      .then(setFederal)
      .catch(() => setFederal([]));
    loadFederalProfile(LAYER_BY_KEY.money_federal_profile.src!)
      .then(setFederalProfile)
      .catch(() => setFederalProfile(null));
  }, []);

  // Labor is profile-only — there is no awards-style geojson beside it, because WHD gives an
  // employer address and no venue. Same swallow-to-null bargain as federal: if the pipeline
  // has not run, the sidebar section and its panel simply do not appear.
  useEffect(() => {
    loadLaborProfile(LAYER_BY_KEY.labor_wage_hour.src!)
      .then(setLaborProfile)
      .catch(() => setLaborProfile(null));
  }, []);

  // A fourth independent load, on the same bargain as federal. It is also the largest file
  // after the spine, so it deliberately does not block anything: the map is usable while it
  // is still in flight, and a venue panel opened early simply shows no context section.
  useEffect(() => {
    loadAcsContext(LAYER_BY_KEY.community_acs.src!)
      .then(setAcs)
      .catch(() => setAcs(null));
  }, []);

  // The boundary files are ~11 MB each, so nothing is fetched until the layer is switched
  // on, and then only the vintage the slider's year is published on. Crossing 2020 fetches
  // the other one once and it stays cached by the browser.
  const zctaVintage = vintageForYear(year);
  useEffect(() => {
    if (!showZcta) return;
    if (zcta?.vintage === zctaVintage) return;
    let cancelled = false;
    setZctaLoading(true);
    loadZctaShapes(LAYER_BY_KEY.community_acs_shapes.src!, zctaVintage)
      .then((s) => {
        if (cancelled) return;
        setZcta(s);
        setZctaError(s ? null : 'ZCTA boundaries have not been emitted yet.');
      })
      .catch((e: Error) => !cancelled && setZctaError(e.message))
      .finally(() => !cancelled && setZctaLoading(false));
    return () => {
      cancelled = true;
    };
  }, [showZcta, zctaVintage, zcta?.vintage]);

  // Which ZCTAs are actually on screen, so the quintile cutoffs rank only what a reader can
  // see rather than the whole country's venue neighbourhoods.
  const drawnZctas = useMemo(() => {
    if (!zcta) return null;
    const ids = new Set<string>();
    for (const f of zcta.features.features) {
      const code = (f.properties as { zcta?: string } | null)?.zcta;
      if (code) ids.add(code);
    }
    return ids;
  }, [zcta]);

  const choropleth = useMemo(
    () => choroplethFor(acs, year, drawnZctas, zctaMetric),
    [acs, year, drawnZctas, zctaMetric]
  );

  // One line per ZCTA for the hover tooltip. Built here rather than in MapView so the map
  // never has to know how a measure is named or formatted, and precomputed rather than
  // formatted per mouse move.
  const zctaLabels = useMemo(() => {
    const out = new Map<string, string>();
    for (const [code, value] of choropleth.values) {
      out.set(code, `ZIP ${code} · ${choropleth.metric.format(value)}`);
    }
    return out;
  }, [choropleth]);

  const zctaPanel = useMemo(
    () => (selectedZcta ? zctaDetail(acs, year, selectedZcta) : null),
    [acs, year, selectedZcta]
  );

  // Resolved against the spine so the panel can print names rather than the venue_ids the
  // ACS payload is keyed by. A venue in the ACS join but not in the spine is skipped rather
  // than shown as a bare id.
  const zctaVenueNames = useMemo(() => {
    if (!zctaPanel || !spine) return [];
    const wanted = new Set(zctaPanel.venueIds);
    return spine.features
      .filter((f) => wanted.has(f.properties.venue_id))
      .map((f) => f.properties.canonical_name);
  }, [zctaPanel, spine]);

  // Switching the layer off leaves no shape to have selected, so the panel goes with it.
  useEffect(() => {
    if (!showZcta) setSelectedZcta(null);
  }, [showZcta]);

  // Year and state, but deliberately not type: a checkbox whose own count went to zero the
  // moment it was unticked would read as "there are none of these" rather than as "you
  // turned these off", and there would be nothing left on the row to turn back on for.
  const typeCountBase = useMemo(() => {
    const ids = new Set<string>();
    if (!spine) return ids;
    for (const f of spine.features) {
      const p = f.properties;
      if (
        (p.opened_year ?? -9999) <= year &&
        (p.closed_year ?? 9999) >= year &&
        (!selectedState || p.state === selectedState)
      ) {
        ids.add(p.venue_id);
      }
    }
    return ids;
  }, [spine, year, selectedState]);

  const typeCounts = useMemo(
    () => (spine ? venueTypeCounts(spine, typeCountBase) : []),
    [spine, typeCountBase]
  );
  const visibleTypes = useMemo(
    () => typeCounts.map((t) => t.type).filter((t) => !hiddenTypes.includes(t)),
    [typeCounts, hiddenTypes]
  );

  // Year and type only. The state dropdown's counts are measured against this rather than
  // against the final set, or every state but the selected one would read (0) — the counts
  // exist to answer "is there anything in Wyoming" *before* Wyoming is picked.
  const preStateVenueIds = useMemo(() => {
    const ids = new Set<string>();
    if (!spine) return ids;
    for (const f of spine.features) {
      const p = f.properties;
      if (
        (p.opened_year ?? -9999) <= year &&
        (p.closed_year ?? 9999) >= year &&
        visibleTypes.includes(p.venue_type)
      ) {
        ids.add(p.venue_id);
      }
    }
    return ids;
  }, [spine, year, visibleTypes]);

  // The venues actually drawn. Every count in the sidebar is derived from this one set, so
  // the legend and the totals cannot disagree about what is on screen.
  const visibleVenueIds = useMemo(() => {
    if (!spine || !selectedState) return preStateVenueIds;
    const ids = new Set<string>();
    for (const f of spine.features) {
      const p = f.properties;
      if (p.state === selectedState && preStateVenueIds.has(p.venue_id)) ids.add(p.venue_id);
    }
    return ids;
  }, [spine, preStateVenueIds, selectedState]);

  const visibleCount = visibleVenueIds.size;

  /**
   * How many of the dots on screen are on screen only because nobody knows when they opened.
   *
   * 4,177 of 6,884 venues (60.7%) have no `opened_date`, and the filter treats an unknown
   * opening as "already open" — the alternative, treating it as closed, would delete more of
   * the spine than it kept. The consequence is that the year readout was a false claim at
   * every position: dragging to 1850 drew 4,191 dots and called them "venues operating in
   * 1850", when 4,177 of them were there because the date is missing. The slider cannot be
   * fixed without the dates, so it says what it is doing instead.
   */
  const undatedVisible = useMemo(() => {
    if (!spine) return 0;
    let n = 0;
    for (const f of spine.features) {
      if (f.properties.opened_year === null && visibleVenueIds.has(f.properties.venue_id)) n++;
    }
    return n;
  }, [spine, visibleVenueIds]);

  const states = useMemo(
    () => stateCounts(spine, preStateVenueIds),
    [spine, preStateVenueIds]
  );
  const statelessVenues = useMemo(() => venuesWithoutState(spine), [spine]);

  /**
   * Picking a state also moves the camera, because a filter that leaves 12 dots somewhere
   * off screen looks identical to a filter that matched nothing. Clearing it does not move
   * the camera back — the user is somewhere on purpose by then.
   */
  const pickState = (code: string | null) => {
    setSelectedState(code);
    const b = boundsForState(spine, code, preStateVenueIds);
    if (b) setFitBounds({ bounds: b, nonce: Date.now() });
  };

  // Palette is keyed on the whole corpus, not on the current year, so an operator does not
  // change color as the slider moves.
  const palette = useMemo(() => operatorPalette(tenure), [tenure]);
  const venueColors = useMemo(
    () => venueColorsAt(tenure, year, palette),
    [tenure, year, palette]
  );
  const legend = useMemo(
    () => operatorLegend(tenure, year, palette, visibleVenueIds),
    [tenure, year, palette, visibleVenueIds]
  );
  const selectedRuns = useMemo(
    () => runsForVenue(tenure, selected?.venue_id),
    [tenure, selected]
  );
  const selectedAwards = useMemo(
    () => awardsForVenue(federal, selected?.venue_id),
    [federal, selected]
  );
  const federalVenueIds = useMemo(
    () => [...new Set(federal.map((a) => a.venue_id))],
    [federal]
  );
  // The figure the sidebar leads with. Kept distinct from the profile total on purpose —
  // see venueAwardTotals for why the two must never be shown as one number.
  const federalVenue = useMemo(() => venueAwardTotals(federal), [federal]);

  // The slider runs 1950-2026 and ACS runs 2011-2024, so most slider positions have no
  // context at all. When the exact year is missing the nearest published year is resolved
  // here and handed to the panel *labelled as a different year* — the panel never presents
  // it as the slider's year.
  const selectedAcs = useMemo(
    () => contextForVenue(acs, selected?.venue_id, year),
    [acs, selected, year]
  );
  const selectedAcsFallback = useMemo(() => {
    if (selectedAcs || !selected) return null;
    const near = nearestYear(acs, selected.venue_id, year);
    return near === null ? null : contextForVenue(acs, selected.venue_id, near);
  }, [acs, selected, year, selectedAcs]);
  const selectedAcsNote = useMemo(
    () => coverageNote(acs, selected?.venue_id),
    [acs, selected]
  );

  // Summed from the legend rather than counted again, so "N have an operator" is by
  // construction the same N the legend rows add up to.
  const coveredVenues = useMemo(
    () => legend.reduce((sum, e) => sum + e.venues, 0),
    [legend]
  );

  /**
   * A search hit has to end up as a dot the user can actually see, and three things can stop
   * that: the venue's type is unchecked, the slider is parked outside its operating window,
   * or the camera is elsewhere. All three are corrected here rather than leaving the user to
   * discover that the thing they searched for is technically on a map they cannot see it on.
   * The state filter is a fourth, and is cleared for the same reason.
   */
  const pickVenue = (hit: VenueHit) => {
    const v = hit.venue;
    if (hiddenTypes.includes(v.venue_type)) {
      setHiddenTypes((prev) => prev.filter((t) => t !== v.venue_type));
    }
    if (selectedState && v.state !== selectedState) setSelectedState(null);
    // Clamped into the venue's own window, not snapped to a fixed year: moving to the
    // nearest year that shows the venue keeps the rest of the user's view intact.
    // Clamped to the slider's own range: a year the slider cannot represent would leave the
    // handle at the floor while the readout claimed a different year.
    if (v.opened_year !== null && year < v.opened_year) setYear(clampYear(v.opened_year));
    else if (v.closed_year !== null && year > v.closed_year) setYear(clampYear(v.closed_year));
    setSelected(v);
    setFlyTo({ lng: hit.lngLat[0], lat: hit.lngLat[1], nonce: Date.now() });
  };

  return (
    <div style={shellStyle}>
      <Sidebar
        spine={spine}
        onPickVenue={pickVenue}
        typeCounts={typeCounts}
        hiddenTypes={hiddenTypes}
        onToggleType={(t) =>
          setHiddenTypes((prev) =>
            prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
          )
        }
        totalVenues={spine?.features.length ?? 0}
        visibleVenues={visibleCount}
        year={year}
        loading={!spine && !error}
        error={error}
        legend={legend}
        coveredVenues={coveredVenues}
        tenureRuns={tenure.length}
        tenureError={tenureError}
        federalProfile={federalProfile}
        federalVenueAwards={federalVenue.awards}
        federalVenueObligated={federalVenue.obligated}
        federalVenueCount={federalVenue.venues}
        federalVenueNames={federalVenue.names}
        // Both panels occupy the same top-left slot, so opening one closes the other rather
        // than stacking a second opaque card on top of the first.
        onShowFederal={() => {
          setShowFederal(true);
          setShowLabor(false);
        }}
        laborProfile={laborProfile}
        onShowLabor={() => {
          setShowLabor(true);
          setShowFederal(false);
        }}
        showZcta={showZcta}
        onToggleZcta={() => setShowZcta((v) => !v)}
        zctaLoading={zctaLoading}
        zctaError={zctaError}
        choropleth={choropleth}
        zctaMetric={zctaMetric}
        onPickZctaMetric={setZctaMetric}
        zctaScopeNote={zcta?.scopeNote ?? null}
        stateCounts={states}
        selectedState={selectedState}
        onPickState={pickState}
        venuesWithoutState={statelessVenues}
      />

      <main style={mapWrapStyle}>
        {/* Only the map is wrapped. A boundary around the whole app would turn a map failure
            into a full-page error screen, which is the outcome this is here to prevent —
            the sidebar carries the evidence and needs no GPU to draw it. */}
        <MapErrorBoundary>
          <MapView
            spine={spine}
            year={year}
            visibleTypes={visibleTypes}
            selectedState={selectedState}
            fitBounds={fitBounds}
            venueColors={venueColors}
            federalVenueIds={federalVenueIds}
            flyTo={flyTo}
            // The two panels occupy the same corner, so opening one closes the other. They are
            // answers to different questions — "what is this venue" and "what is this
            // neighbourhood" — and stacking them would leave the reader unsure which of the
            // two the numbers on screen belong to.
            onSelectVenue={(v) => {
              setSelected(v);
              if (v) setSelectedZcta(null);
            }}
            zctaShapes={showZcta && zcta ? zcta.features : null}
            zctaColors={choropleth.colors}
            zctaLabels={zctaLabels}
            onSelectZcta={(code) => {
              setSelectedZcta(code);
              if (code) setSelected(null);
            }}
            selectedZcta={selectedZcta}
          />
        </MapErrorBoundary>

        <div style={sliderWrapStyle}>
          <div style={sliderHeaderStyle}>
            <span style={{ fontWeight: 600, letterSpacing: '0.02em' }}>{year}</span>
            {/* "venues operating" was the claim; "drawn in" is what the filter does. The
                difference is 4,177 venues wide and the reader could not see it. */}
            <span style={{ color: MUTED }}>
              {visibleCount.toLocaleString()} venues drawn in {year}
            </span>
          </div>
          <Slider
            min={MIN_YEAR}
            max={MAX_YEAR}
            value={year}
            onChange={(v) => setYear(v as number)}
            styles={{
              // Track and handle are ACCENT: they are the control, and 1.4.11 applies to
              // them at 3:1 — 5.93:1 here. The rail is the part of the range not selected,
              // and it uses BORDER_STRONG rather than the decorative BORDER because the rail
              // is what tells you the slider extends past the handle. A rail you cannot see
              // is a slider that looks like it is already at its end.
              track: { backgroundColor: ACCENT },
              handle: { borderColor: ACCENT, backgroundColor: SURFACE, opacity: 1 },
              rail: { backgroundColor: BORDER_STRONG },
            }}
          />
          {undatedVisible > 0 && (
            <p style={sliderNoteStyle}>
              {undatedVisible.toLocaleString()} of them ({Math.round(
                (undatedVisible / Math.max(visibleCount, 1)) * 100
              )}
              %) have no opening date on record, so they are drawn in every year. The slider
              cannot place them, and moving it will not remove them.
            </p>
          )}
        </div>

        {showFederal && (
          <FederalPanel
            profile={federalProfile}
            venueAwards={federalVenue.awards}
            venueObligated={federalVenue.obligated}
            onClose={() => setShowFederal(false)}
          />
        )}

        {showLabor && (
          <LaborPanel profile={laborProfile} onClose={() => setShowLabor(false)} />
        )}

        {zctaPanel && !selected && (
          <ZctaPanel
            detail={zctaPanel}
            activeMetric={zctaMetric}
            venueNames={zctaVenueNames}
            scopeNote={acs?.scope_note ?? null}
            incomeNote={acs?.income_note ?? null}
            onClose={() => setSelectedZcta(null)}
          />
        )}

        {selected && (
          <VenuePanel
            venue={selected}
            year={year}
            runs={selectedRuns}
            awards={selectedAwards}
            acs={selectedAcs}
            acsFallback={selectedAcsFallback}
            acsNote={selectedAcsNote}
            acsScopeNote={acs?.scope_note ?? null}
            acsIncomeNote={acs?.income_note ?? null}
            acsYears={acs?.years ?? []}
            palette={palette}
            onClose={() => setSelected(null)}
          />
        )}
      </main>
    </div>
  );
}

const shellStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '320px 1fr',
  height: '100vh',
  width: '100vw',
  background: SURFACE,
  color: TEXT,
  fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
};

const mapWrapStyle: React.CSSProperties = { position: 'relative', overflow: 'hidden' };

const sliderWrapStyle: React.CSSProperties = {
  position: 'absolute',
  bottom: 24,
  left: 24,
  right: 24,
  padding: '14px 20px 8px',
  background: PANEL_OVER_MAP,
  border: `1px solid ${BORDER}`,
  borderRadius: 10,
  zIndex: 5,
  backdropFilter: 'blur(6px)',
};

const sliderHeaderStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  fontSize: 13,
  marginBottom: 10,
};

// Under the slider rather than beside the count, because it qualifies the whole control and
// not just the number. Sized down but not dimmed past AA — see theme.ts.
const sliderNoteStyle: React.CSSProperties = {
  margin: '2px 0 0',
  fontSize: 11,
  lineHeight: 1.5,
  color: MUTED,
};
