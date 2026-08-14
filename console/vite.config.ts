import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist' },
  // The MapLibre tile-worker fix lives in main.tsx (`setWorkerUrl` + a `?url` import),
  // not here. An earlier fix excluded maplibre-gl from the dep optimizer, which papered
  // over the same silent-worker failure in dev only — `optimizeDeps` has no effect on
  // `vite build`, so production still shipped without the worker file and the map went
  // blank with no console error. The entry-point fix covers both dev and prod.
});
