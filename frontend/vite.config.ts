import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The built SPA is later served by the FastAPI backend and Dockerized in change 7
// proper. The dev proxy target below documents the backend port (8789) but no live
// calls are made in this scaffold pass.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // ws:true so the /api/v1/ws WebSocket upgrade is proxied to the backend
      // under `npm run dev` (otherwise the bridge reconnect-loops forever).
      '/api': { target: 'http://localhost:8789', changeOrigin: true, ws: true },
      '/opds': { target: 'http://localhost:8789', changeOrigin: true },
    },
  },
});
