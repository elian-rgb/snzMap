import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import App from './App';
import './index.css';

// MapLibre spawns its tile worker with `new Worker(new URL('./maplibre-gl-worker.mjs',
// import.meta.url))`. Vite does not emit that URL as an asset when it lives inside a
// dependency, so in a production build it 404s and the worker dies silently — no basemap
// tiles, no GeoJSON dots, and no console error to explain it. The `?worker&url` import
// makes Vite bundle the worker as its own entry — plain `?url` would not do: it copies the
// file verbatim, whose `./maplibre-gl-shared.mjs` import resolves to nothing in dist — and
// `setWorkerUrl` points MapLibre at it before any Map is constructed.
setWorkerUrl(workerUrl);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
