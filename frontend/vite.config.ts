import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Drop emitted font assets that are not .woff2. @fontsource and Font Awesome CSS
 * list several `@font-face` src fallbacks (.woff, .ttf) alongside .woff2, but
 * woff2 is listed FIRST and is universally supported by every browser this app
 * targets, so no browser ever fetches the fallbacks. Shipping them only bloats
 * dist. The now-dangling .woff/.ttf `url()` references left in the CSS are
 * harmless: they are later entries in the same `src:` list and are never
 * reached once woff2 loads. This trims the bundle without touching the CSS.
 */
function dropNonWoff2Fonts(): Plugin {
  const FONT_RE = /\.(woff|ttf|eot|otf)$/i;
  return {
    name: 'foragerr-drop-non-woff2-fonts',
    generateBundle(_options, bundle) {
      for (const fileName of Object.keys(bundle)) {
        if (FONT_RE.test(fileName)) delete bundle[fileName];
      }
    },
  };
}

// The built SPA is later served by the FastAPI backend and Dockerized in change 7
// proper. The dev proxy target below documents the backend port (8789) but no live
// calls are made in this scaffold pass.
export default defineConfig({
  plugins: [react(), dropNonWoff2Fonts()],
  server: {
    proxy: {
      // ws:true so the /api/v1/ws WebSocket upgrade is proxied to the backend
      // under `npm run dev` (otherwise the bridge reconnect-loops forever).
      '/api': { target: 'http://localhost:8789', changeOrigin: true, ws: true },
      '/opds': { target: 'http://localhost:8789', changeOrigin: true },
    },
  },
});
