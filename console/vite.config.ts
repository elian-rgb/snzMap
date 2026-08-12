import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist' },
  // MapLibre spawns its tile worker with `new Worker(new URL('./maplibre-gl-worker.mjs',
  // import.meta.url))`. The dep optimizer rewrites that import but never emits the chunk,
  // so the URL falls through to the SPA index.html and the worker dies silently — no
  // basemap tiles, no GeoJSON dots, and no console error to explain it. Serving maplibre
  // unbundled keeps the worker URL pointing at the real file in node_modules.
  optimizeDeps: { exclude: ['maplibre-gl'] },
});
