import { useEffect, useRef } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { VenueProperties } from '../utils/spineTransform';
import { BASEMAP, BORDER_STRONG, PANEL_OVER_MAP, TEXT } from '../theme';
import { NO_DATA_COLOR } from '../utils/tenureTransform';
import { NO_VALUE_COLOR } from '../utils/zctaChoropleth';

/**
 * MapLibre GL map.
 *
 * Not Leaflet (the dogbo original): Leaflet renders markers as DOM nodes, which falls over
 * at 7k points and cannot repaint on a time slider without re-rendering React. A GL source
 * keeps the data on the GPU, so the slider drives `setFilter` and the repaint is free.
 *
 * Not Mapbox: Mapbox GL requires an account with a card on file even on the free tier.
 * MapLibre is the open-source fork of Mapbox GL JS — same expression syntax, same
 * setFilter/addLayer API — paired with CARTO's positron basemap, which serves vector
 * tiles with no key and no account. Nothing about the layer code below is Mapbox-specific,
 * so the basemap is a one-line change — which is exactly how it moved from dark-matter to
 * positron when the console went light.
 */

// Keyless. CARTO asks for attribution, which their style.json already includes.
const STYLE_URL = BASEMAP;

const SPINE_SOURCE = 'venue-spine';
const SPINE_LAYER = 'venue-spine-circles';
const FEDERAL_LAYER = 'venue-federal-ring';
const ZCTA_SOURCE = 'acs-zcta';
const ZCTA_FILL = 'acs-zcta-fill';
const ZCTA_LINE = 'acs-zcta-line';
const ZCTA_HOVER = 'acs-zcta-hover';

/**
 * venue_id -> color, as a GL `match` expression.
 *
 * Grouped by color rather than emitted as one pair per venue: `match` accepts an array of
 * labels per output, so eight operators produce an expression with eight branches instead of
 * one branch per venue. The fallback is the gray, which is what makes "no operator on record"
 * a rendering decision rather than an omission — the venue is still drawn.
 */
function matchColors(
  key: string,
  colors: Map<string, string>,
  fallback: string
): maplibregl.ExpressionSpecification | string {
  if (colors.size === 0) return fallback;

  const byColor = new Map<string, string[]>();
  for (const [id, color] of colors) {
    const ids = byColor.get(color);
    if (ids) ids.push(id);
    else byColor.set(color, [id]);
  }

  const branches: unknown[] = [];
  for (const [color, ids] of byColor) branches.push(ids, color);
  return ['match', ['get', key], ...branches, fallback] as
    unknown as maplibregl.ExpressionSpecification;
}

function colorExpression(venueColors: Map<string, string>) {
  return matchColors('venue_id', venueColors, NO_DATA_COLOR);
}

/** A filter that matches nothing, for the outline layer when nothing is hovered or picked.
 *  The layer is always present and always filtered, so there is no frame in which it exists
 *  unfiltered and outlines all 4,087 polygons at once. Filtering rather than toggling
 *  `visibility` keeps a mouse move off the style-recalculation path. */
const HOVER_NONE = ['==', ['get', 'zcta'], '\u0000'] as
  unknown as maplibregl.FilterSpecification;

export interface MapViewProps {
  spine: GeoJSON.FeatureCollection | null;
  /** Year the time slider is parked on; venues not yet open / already closed drop out. */
  year: number;
  visibleTypes: string[];
  /**
   * Two-letter state the sidebar is filtering to, or null for all of them. Applied to the
   * same GL filter as year and type rather than by rebuilding the source, so picking a state
   * costs the same as moving the slider.
   */
  selectedState: string | null;
  /**
   * Where to frame the current state selection, with a nonce so re-picking the same state
   * refits. Null when nothing is selected — the camera is then left exactly where the user
   * put it, since zooming back out is a decision they did not ask for.
   */
  fitBounds: { bounds: [[number, number], [number, number]]; nonce: number } | null;
  /** Which operator holds each venue in `year`, already collapsed to one color per venue. */
  venueColors: Map<string, string>;
  /** Venues that a federal award names. Drawn as a ring, not as its own dot. */
  federalVenueIds: string[];
  /**
   * Venue ids the neighbourhood band filter left standing, or null when no band is ticked.
   *
   * Null rather than "all the ids" on purpose: `in` over a literal array is a linear scan per
   * feature, and the default state of this control is off. Passing the full spine every render
   * would make the common case the expensive one.
   */
  bandVenueIds: string[] | null;
  /**
   * Where search wants the camera. The `nonce` is what makes picking the same venue twice
   * fly again — without it the effect's dependencies are unchanged and the map sits still,
   * which reads as a broken search box.
   */
  flyTo: { lng: number; lat: number; nonce: number } | null;
  onSelectVenue: (venue: VenueProperties | null) => void;
  /** Boundaries for the slider year's ZCTA vintage. Null until the user asks for them. */
  zctaShapes: GeoJSON.FeatureCollection | null;
  /** zcta -> fill color. Empty means "drawn, but nothing to shade it by". */
  zctaColors: Map<string, string>;
  /**
   * zcta -> the one line the hover tooltip shows. Built by the caller so this component
   * never has to know how a measure is formatted or what it is called. A code missing from
   * the map still gets a tooltip — see `onHoverZcta`'s fallback — because a silent tooltip
   * would make "no estimate published" look like "hover is broken here".
   */
  zctaLabels: Map<string, string>;
  onSelectZcta: (zcta: string | null) => void;
  /** Which ZCTA the panel is open on, so the map can keep it outlined. */
  selectedZcta: string | null;
}

export function MapView({
  spine,
  year,
  visibleTypes,
  selectedState,
  fitBounds,
  venueColors,
  federalVenueIds,
  bandVenueIds,
  flyTo,
  onSelectVenue,
  zctaShapes,
  zctaColors,
  zctaLabels,
  onSelectZcta,
  selectedZcta,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const onSelectRef = useRef(onSelectVenue);
  onSelectRef.current = onSelectVenue;
  // Read through refs by the map's own event handlers, which are installed once and would
  // otherwise close over the first render's values forever.
  const onSelectZctaRef = useRef(onSelectZcta);
  onSelectZctaRef.current = onSelectZcta;
  const zctaLabelsRef = useRef(zctaLabels);
  zctaLabelsRef.current = zctaLabels;
  // Hover and selection share one outline layer, so leaving a hover has to fall back to the
  // selected ZCTA rather than to nothing — otherwise moving the mouse off a polygon erases
  // the outline around the one whose panel is still open.
  const selectedZctaRef = useRef(selectedZcta);
  selectedZctaRef.current = selectedZcta;
  // Read at install time: the two files load independently, and if tenure arrives first the
  // recolor effect below has already run against a layer that did not exist yet.
  const venueColorsRef = useRef(venueColors);
  venueColorsRef.current = venueColors;

  // ── Map init (once) ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    // Checked before anything is constructed, and that ordering is the whole point. MapLibre
    // does raise its own "WebGL2 is required" error, but only from inside the Map constructor
    // after it has half-built itself — and tearing that half-built map down raises a *second*
    // error, which is the one an error boundary above actually receives. Measured on a browser
    // with WebGL denied: the boundary was handed "Cannot read properties of undefined (reading
    // 'destroy')" and told the reader nothing about the cause. Failing here instead means the
    // accurate message is the one that propagates, and there is nothing half-built to unwind.
    if (!document.createElement('canvas').getContext('webgl2')) {
      throw new Error(
        'This browser did not provide a WebGL2 context, which the map needs to draw.'
      );
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.4,
      minZoom: 2,
      maxZoom: 16,
    });
    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => {
      loadedRef.current = true;
      map.resize();
    });

    // ZCTA hover + click, installed once. MapLibre accepts a layer-scoped listener for a
    // layer that does not exist yet and simply never fires it, which is what makes this
    // safe here — registering them where the layer is created would stack a fresh copy
    // every time the user toggled the layer off and on.
    const outline = (code: string | null) => {
      if (!map.getLayer(ZCTA_HOVER)) return;
      map.setFilter(
        ZCTA_HOVER,
        code === null
          ? HOVER_NONE
          : (['==', ['get', 'zcta'], code] as unknown as maplibregl.FilterSpecification)
      );
    };

    const clearHover = () => {
      outline(selectedZctaRef.current);
      if (tooltipRef.current) tooltipRef.current.style.display = 'none';
      map.getCanvas().style.cursor = '';
    };

    map.on('mousemove', ZCTA_FILL, (e: maplibregl.MapLayerMouseEvent) => {
      const code = (e.features?.[0]?.properties as { zcta?: string } | undefined)?.zcta;
      const tip = tooltipRef.current;
      if (!code || !tip) return clearHover();

      outline(code);
      // A ZCTA with no label is one ACS published no estimate for, which is a fact about
      // the data and is said out loud rather than shown as an empty tooltip.
      tip.textContent = zctaLabelsRef.current.get(code) ?? `ZIP ${code} \u00b7 no estimate`;
      tip.style.display = 'block';
      // Set on every move rather than on mouseenter, because the spine layer's own
      // mouseleave clears the cursor when the pointer slides off a dot onto the shading
      // underneath — which is still clickable. Reasserting it here is self-correcting.
      map.getCanvas().style.cursor = 'pointer';
      // Flipped to the other side of the cursor near the right or bottom edge, where a
      // tooltip that always sat down-right would be clipped by the map container.
      const { x, y } = e.point;
      const box = map.getContainer().getBoundingClientRect();
      const flipX = x + tip.offsetWidth + 24 > box.width;
      const flipY = y + tip.offsetHeight + 24 > box.height;
      tip.style.left = `${flipX ? x - tip.offsetWidth - 14 : x + 14}px`;
      tip.style.top = `${flipY ? y - tip.offsetHeight - 14 : y + 14}px`;
    });

    map.on('mouseleave', ZCTA_FILL, clearHover);

    map.on('click', ZCTA_FILL, (e: maplibregl.MapLayerMouseEvent) => {
      // The venue dots sit above the shading, and a click that lands on one is about the
      // venue. Both layers' click handlers fire for the same click, so without this the
      // ZCTA panel would open on top of every venue the user selected.
      const onVenue =
        map.getLayer(SPINE_LAYER) &&
        map.queryRenderedFeatures(e.point, { layers: [SPINE_LAYER] }).length > 0;
      if (onVenue) return;
      const code = (e.features?.[0]?.properties as { zcta?: string } | undefined)?.zcta;
      if (code) onSelectZctaRef.current(code);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []);

  // ── Spine source + layer ───────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !spine) return;

    const install = () => {
      if (map.getSource(SPINE_SOURCE)) {
        (map.getSource(SPINE_SOURCE) as maplibregl.GeoJSONSource).setData(spine);
        return;
      }

      map.addSource(SPINE_SOURCE, { type: 'geojson', data: spine });
      map.addLayer({
        id: SPINE_LAYER,
        type: 'circle',
        source: SPINE_SOURCE,
        paint: {
          // Capacity is missing for most venues, so size falls back to a small dot
          // rather than hiding the venue.
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3,
            ['case', ['>', ['coalesce', ['get', 'capacity'], 0], 40000], 4, 2.2],
            10,
            ['case', ['>', ['coalesce', ['get', 'capacity'], 0], 40000], 12, 6],
          ],
          'circle-color': colorExpression(venueColorsRef.current),
          'circle-opacity': venueColorsRef.current.size === 0 ? 0.88 : 0.92,
          // The halo is white and wider than it was dark. It is a separator, not the contrast
          // guarantee — the guarantee is the dot fill itself, which clears 3:1 against
          // positron's land and water and against all five composited ACS bins (see the
          // measured table in zctaChoropleth.ts). The halo is invisible against land at
          // 1.05:1 and only 1.08–1.13:1 against the bins, so it cannot be doing that job and
          // must not be described as if it were.
          //
          // What it does do is give the dot an edge of its own when it lands on a ZCTA of
          // similar weight, and keep two adjacent dots in a dense metro from reading as one
          // blob. Both are legibility, neither is 1.4.11, and keeping that distinction
          // straight is what stopped the ramp from being tuned against the wrong number.
          'circle-stroke-width': 1,
          'circle-stroke-color': '#ffffff',
        },
      });

      // A federal award is not a place of its own — it is a fact about a venue already on
      // the map. So it is a ring drawn under that venue's dot, from the same source, rather
      // than a second point that would sit on top of the first and double the count.
      map.addLayer(
        {
          id: FEDERAL_LAYER,
          type: 'circle',
          source: SPINE_SOURCE,
          // Starts matching nothing. Without an explicit filter the layer would ring every
          // venue on the map for the frame between install and the filter effect.
          filter: ['in', ['get', 'venue_id'], ['literal', []]],
          paint: {
            'circle-radius': [
              'interpolate',
              ['linear'],
              ['zoom'],
              3,
              5.5,
              10,
              14,
            ],
            'circle-color': 'rgba(0,0,0,0)',
            'circle-stroke-width': 1.6,
            // Was a bright amber picked to glow on navy; on positron it measured 2.06:1 on
            // land and 1.52:1 on water, a ring marking the eight most consequential venues
            // on the map that you could only see if you already knew where they were.
            // 6.56:1 / 4.85:1 instead. Kept darker than the palette's own amber (#b45309) so
            // "has a federal award" and "operated by whoever holds the amber slot" do not
            // read as the same mark once tenure data lands.
            'circle-stroke-color': '#854d0e',
          },
        },
        SPINE_LAYER
      );

      map.on('click', SPINE_LAYER, (e: maplibregl.MapLayerMouseEvent) => {
        const f = e.features?.[0] as { properties?: unknown } | undefined;
        if (f?.properties) onSelectRef.current(f.properties as VenueProperties);
      });
      map.on('mouseenter', SPINE_LAYER, () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', SPINE_LAYER, () => {
        map.getCanvas().style.cursor = '';
      });
    };

    if (loadedRef.current) install();
    else map.once('load', install);
  }, [spine]);

  // ── ZCTA choropleth ────────────────────────────────────────────────────────
  // Added and removed rather than toggled to `visibility: none`, because the geometry is
  // ~11 MB per vintage and keeping a hidden copy of it parsed on the GPU costs the same as
  // showing it. `zctaShapes` going null is the user switching the layer off.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!zctaShapes) {
        if (map.getLayer(ZCTA_HOVER)) map.removeLayer(ZCTA_HOVER);
        if (map.getLayer(ZCTA_LINE)) map.removeLayer(ZCTA_LINE);
        if (map.getLayer(ZCTA_FILL)) map.removeLayer(ZCTA_FILL);
        if (map.getSource(ZCTA_SOURCE)) map.removeSource(ZCTA_SOURCE);
        if (tooltipRef.current) tooltipRef.current.style.display = 'none';
        return;
      }

      const source = map.getSource(ZCTA_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (source) {
        // The vintage switch lands here: same source, different boundaries.
        source.setData(zctaShapes);
      } else {
        map.addSource(ZCTA_SOURCE, { type: 'geojson', data: zctaShapes });
        // Beneath the venue dots, so a shaded neighbourhood never hides the venue it
        // describes. The spine layer may not exist yet if the shape file wins the race.
        const beneath = map.getLayer(ZCTA_FILL) ? undefined : map.getLayer(FEDERAL_LAYER)
          ? FEDERAL_LAYER
          : map.getLayer(SPINE_LAYER)
            ? SPINE_LAYER
            : undefined;
        map.addLayer(
          {
            id: ZCTA_FILL,
            type: 'fill',
            source: ZCTA_SOURCE,
            paint: {
              'fill-color': matchColors('zcta', zctaColors, NO_VALUE_COLOR),
              // Low enough that the basemap's streets still read through it: the shading is
              // context for the dots, not a replacement for the map underneath.
              'fill-opacity': 0.55,
            },
          },
          beneath
        );
        map.addLayer(
          {
            id: ZCTA_LINE,
            type: 'line',
            source: ZCTA_SOURCE,
            // Decorative, in the same sense as the sidebar's divider token: which bin a ZCTA
            // is in is carried by the fill and the legend's cutoffs, and *which* ZCTA you are
            // pointing at is carried by ZCTA_HOVER below — which does pass 1.4.11 on every
            // bin. So this hairline is free to stay quiet. A boundary dark enough to clear
            // 3:1 on the darkest bin, drawn once per ZCTA, is a mesh over the whole country.
            paint: { 'line-color': '#475569', 'line-width': 0.4, 'line-opacity': 0.45 },
          },
          beneath
        );
        // The outline for whatever is hovered or selected. Above the other two ZCTA layers,
        // but still under the venue dots, so pointing at a neighbourhood never covers the
        // venues that are the reason it is drawn.
        //
        // Dark rather than the accent blue: this outline is drawn on top of a blue ramp, and
        // a blue line on blue shading is a line you have to hunt for on exactly the bins where
        // the data is densest. 17.08:1 on land and 5.77:1 on the darkest bin — the one element
        // of the ZCTA layer that has to be unmissable on all five, because it is the only
        // thing that says which polygon the panel is about.
        map.addLayer(
          {
            id: ZCTA_HOVER,
            type: 'line',
            source: ZCTA_SOURCE,
            filter: HOVER_NONE,
            paint: { 'line-color': '#0f172a', 'line-width': 1.6 },
          },
          beneath
        );
      }
      map.setPaintProperty(
        ZCTA_FILL,
        'fill-color',
        matchColors('zcta', zctaColors, NO_VALUE_COLOR)
      );
    };

    if (loadedRef.current) apply();
    else map.once('load', apply);
  }, [zctaShapes, zctaColors]);

  // ── Selected ZCTA outline ──────────────────────────────────────────────────
  // Selection can change without the mouse — closing the panel, or the layer being switched
  // off — so the outline is driven from the prop rather than only from the hover handler.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer(ZCTA_HOVER)) return;
    map.setFilter(
      ZCTA_HOVER,
      selectedZcta === null
        ? HOVER_NONE
        : (['==', ['get', 'zcta'], selectedZcta] as unknown as maplibregl.FilterSpecification)
    );
  }, [selectedZcta, zctaShapes]);

  // ── Time + type filter ─────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!map.getLayer(SPINE_LAYER)) return;
      // opened_year/closed_year are precomputed as numbers in spineTransform; GL
      // expressions cannot parse date strings, and a null means "unknown", which must
      // stay visible rather than being filtered out as if it were false.
      const clauses: unknown[] = [
        'all',
        ['<=', ['coalesce', ['get', 'opened_year'], -9999], year],
        ['>=', ['coalesce', ['get', 'closed_year'], 9999], year],
        ['in', ['get', 'venue_type'], ['literal', visibleTypes]],
      ];
      // 1,085 venues carry no state, and `['==', ['get','state'], 'TX']` drops them. That is
      // the intended behaviour — the sidebar says so out loud rather than letting them
      // vanish unexplained.
      if (selectedState) clauses.push(['==', ['get', 'state'], selectedState]);
      // The band filter arrives as an id list because it is computed from ACS rows keyed by
      // venue, not from anything carried on the feature. Venues with no ACS row for this year
      // are already in the list — App unions them in rather than letting a missing row read as
      // a failed test.
      //
      // `match` rather than `in`, and this is not a style preference. `in` over a literal
      // array is a linear scan per feature: at 6,884 features against a 6,469-id list that is
      // ~44M string comparisons on the main thread, which locked the renderer hard enough that
      // an eval against the page timed out. `match` compiles its labels to a hash lookup, so
      // the same filter is O(1) per feature and ticking all four bands is instant.
      //
      // An empty list would be an invalid `match`, so it becomes an explicit never-match. That
      // case should not arise — App sends null when no band is ticked — but a filter that
      // throws would take the whole spine layer off the map.
      if (bandVenueIds) {
        clauses.push(
          bandVenueIds.length === 0
            ? ['==', ['get', 'venue_id'], '\u0000']
            : ['match', ['get', 'venue_id'], bandVenueIds, true, false]
        );
      }
      map.setFilter(SPINE_LAYER, clauses as unknown as maplibregl.FilterSpecification);
      // The ring inherits the same visibility rules, so a venue filtered off the map
      // cannot leave its federal ring behind. The clauses are spread rather than nesting
      // the spine filter inside a second `all`: MapLibre tolerates the nesting at runtime
      // but its types do not, and a flat list is what the expression spec actually means.
      map.setFilter(FEDERAL_LAYER, [
        ...clauses,
        ['in', ['get', 'venue_id'], ['literal', federalVenueIds]],
      ] as unknown as maplibregl.FilterSpecification);
    };

    if (loadedRef.current) apply();
    else map.once('load', apply);
  }, [year, visibleTypes, selectedState, federalVenueIds, bandVenueIds]);

  // ── Frame the state selection ──────────────────────────────────────────────
  // Bounds come from the dots the filter left, not from a state outline, so a state whose
  // venues cluster in one corner frames that corner. Padded because a fit to the exact
  // extent puts the outermost venues on the window edge, where they are half-drawn.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitBounds) return;
    map.fitBounds(fitBounds.bounds, { padding: 60, duration: 900, maxZoom: 11 });
  }, [fitBounds]);

  // ── Tenure color ───────────────────────────────────────────────────────────
  // The tenure layer is not a second source. One venue is one dot, and the question the
  // map answers is "who ran this place in year T", so the answer belongs in the dot's
  // color. Recoloring is a paint-property change on a layer already on the GPU, so the
  // slider stays as cheap as it was when every dot was gray.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const paint = () => {
      if (!map.getLayer(SPINE_LAYER)) return;
      map.setPaintProperty(SPINE_LAYER, 'circle-color', colorExpression(venueColors));
      // Known operators sit slightly brighter than the gray, so a colored venue reads as
      // an assertion and a gray one reads as a gap rather than as background.
      map.setPaintProperty(
        SPINE_LAYER,
        'circle-opacity',
        venueColors.size === 0 ? 0.88 : 0.92
      );
    };

    if (loadedRef.current) paint();
    else map.once('load', paint);
  }, [venueColors]);

  // ── Fly to a searched venue ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTo) return;
    // Zoom 13 rather than the max: close enough to read the street the venue is on, far
    // enough that its neighbours stay visible, which is the context that makes a search
    // result checkable rather than just centred.
    map.flyTo({ center: [flyTo.lng, flyTo.lat], zoom: 13, speed: 1.4 });
  }, [flyTo]);

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
      {/* Positioned by the mousemove handler rather than by React state: at 4,087 polygons
          a setState per mouse move would re-render the whole tree on every frame of a drag
          across the map. `pointerEvents: none` keeps it from stealing the hover it
          describes, which would make it flicker as it chased the cursor. */}
      <div ref={tooltipRef} style={tooltipStyle} />
    </div>
  );
}

const tooltipStyle: React.CSSProperties = {
  position: 'absolute',
  display: 'none',
  pointerEvents: 'none',
  zIndex: 7,
  padding: '5px 9px',
  background: PANEL_OVER_MAP,
  border: `1px solid ${BORDER_STRONG}`,
  borderRadius: 6,
  color: TEXT,
  fontSize: 12,
  whiteSpace: 'nowrap',
};
