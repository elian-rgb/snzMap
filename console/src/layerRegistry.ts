/**
 * Central layer list. Every layer in the console is declared here and nowhere else —
 * the sidebar, the legend, and the map all read from this array.
 *
 * `geometry` is what the map needs to know; `recordType` is what the data contract calls
 * it (see SNZ_PLAN_v2 §0). A layer whose file has not been produced yet is `status:
 * 'planned'` — it still renders in the sidebar, disabled, because a layer we know we want
 * and do not yet have is information worth showing.
 */

export type LayerCategory =
  | 'spine'
  | 'contract'
  | 'money'
  | 'labor'
  | 'community'
  | 'workforce'
  | 'ops';

/** `none` is a real answer: some sources are about an operator, not about a place, and
 *  giving them coordinates would be an invention rather than a rendering.
 *  `zcta` is deliberately distinct from `tract`: a ZCTA is a postal-delivery area an order
 *  of magnitude coarser than a tract, and calling it one would overstate the resolution. */
export type LayerGeometry = 'point' | 'tract' | 'zcta' | 'county' | 'line' | 'none';

export type LayerStatus = 'ready' | 'planned';

export interface LayerDef {
  key: string;
  label: string;
  category: LayerCategory;
  geometry: LayerGeometry;
  /** Record type from the data contract: A = event, B = tenure, C = observation. */
  recordType: 'spine' | 'A' | 'B' | 'C';
  status: LayerStatus;
  /** Path under /data for ready layers. */
  src?: string;
  source: string;
  description: string;
}

export const LAYER_REGISTRY: LayerDef[] = [
  // ── Spine + contract history (the project's own data) ──────────────────────
  {
    key: 'venue_spine',
    label: 'Venue spine',
    category: 'spine',
    geometry: 'point',
    recordType: 'spine',
    status: 'ready',
    src: '/data/venues.geojson',
    source: 'Wikidata + OpenStreetMap',
    description:
      'Census of US stadiums, arenas and convention centers, including defunct ones. ' +
      'Gray = no known operator, which is a documented gap rather than an absence of history.',
  },
  {
    key: 'contract_tenure',
    label: 'Contract tenure',
    category: 'contract',
    geometry: 'point',
    recordType: 'B',
    status: 'ready',
    src: '/data/tenure_records.geojson',
    source: 'Article extraction pipeline',
    description:
      "One row per operator's run at one venue. At time T a venue shows the operator whose span contains T. " +
      'Covers 7 venues out of 6,884 — a sample of what the corpus supports, not a census.',
  },
  {
    key: 'contract_events',
    label: 'Contract events',
    category: 'contract',
    geometry: 'point',
    recordType: 'A',
    status: 'ready',
    src: '/data/contract_events.geojson',
    source: 'Article extraction pipeline',
    description:
      'Individual won/lost/renewed/self-op contract claims as reported by newspaper articles. ' +
      'Ringed in magenta on the map, one ring per venue; repeat coverage of one award is ' +
      'folded into a single claim. The coverage fraction is in the sidebar, read off the ' +
      'data — a figure typed here would still be quoted after the corpus had changed.',
  },

  // ── Money ─────────────────────────────────────────────────────────────────
  {
    key: 'money_nyc_payments',
    label: 'NYC payments',
    category: 'money',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'Checkbook NYC',
    description: 'City payments to food service vendors, sized by dollar value.',
  },
  {
    key: 'money_nonprofit_990',
    label: 'Nonprofit 990s',
    category: 'money',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'ProPublica Nonprofit Explorer',
    description: 'Filings for institutions that contract out food service.',
  },
  {
    key: 'money_federal',
    label: 'Federal awards',
    category: 'money',
    geometry: 'point',
    recordType: 'C',
    status: 'ready',
    src: '/data/federal_venue_awards.geojson',
    source: 'USAspending',
    description:
      'Federal food-service awards that name a venue in the spine and whose place-of-' +
      'performance ZIP falls in that venue’s ZCTA. Eight of 9,672 — federal food service ' +
      'happens on military posts and in VA hospitals, which this spine does not contain.',
  },
  {
    key: 'money_federal_profile',
    label: 'Federal spending by operator',
    category: 'money',
    geometry: 'none',
    recordType: 'C',
    status: 'ready',
    src: '/data/federal_operator_profile.json',
    source: 'USAspending',
    description:
      '$5.0B of in-scope federal food-service obligations across 393 awards. Deliberately ' +
      'not a map layer: an operator\u2019s federal revenue is a fact about the operator, and ' +
      'spreading it over venues would invent a geography the data does not have.',
  },

  // ── Labor ─────────────────────────────────────────────────────────────────
  {
    key: 'labor_wage_hour',
    label: 'Wage & hour by operator',
    category: 'labor',
    geometry: 'none',
    recordType: 'C',
    status: 'ready',
    src: '/data/labor_whd_profile.json',
    source: 'DOL WHD (WHISARD), via the labordata.bunkum.us mirror',
    description:
      '231 concluded wage-and-hour cases against these operators, $2.1M in back wages to ' +
      '2,459 workers. Operator-level only: 840 rows matched a company name loosely and 493 ' +
      'were other companies entirely — Compass Bank alone was 80.',
  },
  {
    key: 'labor_wage_hour_venues',
    label: 'Wage & hour by venue',
    category: 'labor',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'DOL WHD (WHISARD)',
    description:
      'Blocked, not unbuilt. WHISARD records an employer establishment address and never a ' +
      'venue name, so there is nothing to join on but ZIP — which put the 179 geocodable ' +
      'cases across 420 distinct venues. One Raleigh ZIP alone yields nine.',
  },
  {
    key: 'labor_nlrb_osha',
    label: 'NLRB / OSHA actions',
    category: 'labor',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'NLRB, OSHA',
    description: 'Union elections, unfair labor practice charges, safety inspections.',
  },

  // ── Community context ─────────────────────────────────────────────────────
  {
    key: 'community_places',
    label: 'CDC PLACES health',
    category: 'community',
    geometry: 'tract',
    recordType: 'C',
    status: 'planned',
    source: 'CDC PLACES',
    description: 'Tract-level chronic disease and health behavior estimates.',
  },
  {
    key: 'community_life_expectancy',
    label: 'Life expectancy',
    category: 'community',
    geometry: 'tract',
    recordType: 'C',
    status: 'planned',
    source: 'USALEEP',
    description: 'Census tract life expectancy at birth.',
  },
  {
    key: 'community_food_access',
    label: 'Food access',
    category: 'community',
    geometry: 'tract',
    recordType: 'C',
    status: 'planned',
    source: 'USDA Food Access Research Atlas',
    description: 'Low-income / low-access tract designations.',
  },
  {
    key: 'community_acs',
    label: 'ACS context',
    category: 'community',
    geometry: 'zcta',
    recordType: 'C',
    status: 'ready',
    src: '/data/acs_venue_context.json',
    source: 'Census ACS 5-year, 2011\u20132024',
    description:
      'Workers, median household income, transit share and long-commute share for the ZCTA ' +
      'around each venue, 6,831 of 6,884 venues. A ZCTA is a postal-delivery area, not the ' +
      'venue \u2014 read it as neighbourhood context, never as evidence about the venue. ' +
      'Income is in each vintage year\u2019s own dollars and is not a real-terms trend.',
  },
  {
    key: 'community_acs_shapes',
    label: 'ACS context areas',
    category: 'community',
    geometry: 'zcta',
    recordType: 'C',
    status: 'ready',
    // Two files, one per ZCTA definition. Only the one covering the slider's year is ever
    // fetched, so `src` is a prefix completed with the vintage rather than a single path.
    src: '/data/acs_zcta_',
    source: 'Census cartographic boundary files, 2019 (2010 ZCTAs) + 2020',
    description:
      'Boundaries for the 4,087 ZCTAs that contain a venue \u2014 12% of the country. ' +
      'Everywhere else is blank because no venue is there, not because it was not measured. ' +
      'Shading is the ZCTA\u2019s figure, never the venue\u2019s. Boundaries switch definition ' +
      'in 2021 with the ACS, so shapes change shape when the slider crosses it.',
  },

  // ── Workforce + operations ────────────────────────────────────────────────
  {
    key: 'workforce_qcew',
    label: 'QCEW food service wages',
    category: 'workforce',
    geometry: 'county',
    recordType: 'C',
    status: 'planned',
    source: 'BLS QCEW',
    description: 'County average weekly wage for food service employment.',
  },
  {
    key: 'ops_inspections',
    label: 'Health inspections',
    category: 'ops',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'City open data portals',
    description:
      'Restaurant inspection results. Caveat: institutional kitchens are often outside the restaurant inspection regime.',
  },
  {
    key: 'ops_energy_waste',
    label: 'Energy & waste',
    category: 'ops',
    geometry: 'point',
    recordType: 'C',
    status: 'planned',
    source: 'NYC LL84, DSNY commercial waste zones',
    description: 'Building energy benchmarking and commercial waste hauling.',
  },
];

export const CATEGORY_LABELS: Record<LayerCategory, string> = {
  spine: 'Venue spine',
  contract: 'Contract history',
  money: 'Money',
  labor: 'Labor',
  community: 'Community',
  workforce: 'Workforce',
  ops: 'Operations',
};

export const LAYER_BY_KEY: Record<string, LayerDef> = Object.fromEntries(
  LAYER_REGISTRY.map((l) => [l.key, l])
);
