import { useEffect, useMemo, useRef, useState } from 'react';
import { ACCENT_SOFT, BORDER_STRONG, MUTED, SURFACE, TEXT, WARN } from '../theme';
import type { VenueProperties } from '../utils/spineTransform';
import { hitSubtitle, searchVenues, type VenueHit } from '../utils/venueSearch';

interface VenueSearchProps {
  spine: GeoJSON.FeatureCollection<GeoJSON.Point, VenueProperties> | null;
  year: number;
  onPick: (hit: VenueHit) => void;
}

/**
 * Type-to-find over the whole spine.
 *
 * Searching every feature on every keystroke is ~7k string comparisons, which measures
 * under a millisecond — so there is no debounce and no index. Adding either would be
 * complexity bought with nothing.
 *
 * The result list deliberately shows venues that are *not currently on the map*: a venue
 * closed in 1968 will not be drawn at slider year 2015, and hiding it from search would
 * make it look absent from the spine when it is not. Picking one moves the slider instead.
 */
export function VenueSearch({ spine, year, onPick }: VenueSearchProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const hits = useMemo(() => searchVenues(spine, query), [spine, query]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  const choose = (hit: VenueHit) => {
    onPick(hit);
    setOpen(false);
    setQuery(hit.venue.canonical_name);
  };

  return (
    <div ref={boxRef} style={wrapStyle}>
      <input
        value={query}
        placeholder={'Find a venue\u2026   MSG, Barclays, Staples Center'}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setCursor((c) => Math.min(c + 1, hits.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setCursor((c) => Math.max(c - 1, 0));
          } else if (e.key === 'Enter' && hits[cursor]) {
            choose(hits[cursor]);
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
        style={inputStyle}
        aria-label="Find a venue by name"
      />

      {open && query.trim().length >= 2 && (
        <ul style={dropStyle}>
          {hits.length === 0 && (
            <li style={{ ...emptyStyle }}>
              No venue matches &ldquo;{query}&rdquo;. Old names are searched too, so this is
              a real absence from the spine rather than a renamed venue hiding.
            </li>
          )}
          {hits.map((hit, i) => {
            const closed = hit.venue.closed_year !== null && hit.venue.closed_year < year;
            const unopened =
              hit.venue.opened_year !== null && hit.venue.opened_year > year;
            return (
              <li key={hit.venue.venue_id}>
                <button
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => choose(hit)}
                  style={{
                    ...hitStyle,
                    background: i === cursor ? ACCENT_SOFT : 'transparent',
                  }}
                >
                  <span style={hitNameStyle}>{hit.venue.canonical_name}</span>
                  <span style={hitSubStyle}>
                    {hitSubtitle(hit, year)}
                    {/* Said out loud rather than filtered away: the venue is in the spine,
                        it is simply not drawn at this slider year. Picking it moves the
                        slider, so the dot the user was promised actually appears. */}
                    {(closed || unopened) && (
                      <span style={offMapStyle}>
                        {closed ? ' \u00b7 not on the map in ' : ' \u00b7 not built yet in '}
                        {year}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const wrapStyle: React.CSSProperties = { position: 'relative', marginBottom: 16 };

const inputStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '8px 10px',
  background: SURFACE,
  border: `1px solid ${BORDER_STRONG}`,
  borderRadius: 6,
  color: TEXT,
  fontSize: 12.5,
  outline: 'none',
};

const dropStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  right: 0,
  marginTop: 4,
  listStyle: 'none',
  padding: 4,
  background: SURFACE,
  border: `1px solid ${BORDER_STRONG}`,
  borderRadius: 6,
  maxHeight: 320,
  overflowY: 'auto',
  zIndex: 20,
  boxShadow: '0 10px 24px rgba(15,23,42,0.14)',
};

const hitStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '6px 8px',
  border: 'none',
  borderRadius: 4,
  color: TEXT,
  cursor: 'pointer',
  font: 'inherit',
};

const hitNameStyle: React.CSSProperties = { display: 'block', fontSize: 12.5 };
const hitSubStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11,
  color: MUTED,
  marginTop: 1,
};
const offMapStyle: React.CSSProperties = { color: WARN };
const emptyStyle: React.CSSProperties = {
  padding: '8px 8px',
  fontSize: 11,
  color: MUTED,
  lineHeight: 1.5,
};
