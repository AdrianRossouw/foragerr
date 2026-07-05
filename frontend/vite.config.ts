import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The built SPA is later served by the FastAPI backend and Dockerized in change 7
// proper. The dev proxy target below documents the backend port (8789) but no live
// calls are made in this scaffold pass.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8789', changeOrigin: true },
      '/opds': { target: 'http://localhost:8789', changeOrigin: true },
    },
  },
});
