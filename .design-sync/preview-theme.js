// design-sync bundle support module (not part of the app build). Pulls the
// global style surface that main.tsx assembles via JS imports — token layer +
// base styles plus the vendored Roboto and Font Awesome CSS — into
// _ds_bundle.css so synced designs render with the exact closure the real SPA
// ships. esbuild resolves the CSS @imports and inlines the font binaries as
// data URLs, keeping the uploaded bundle self-contained (no CDN fetches —
// matches the app's FRG-UI-002 egress posture). Keep in step with main.tsx's
// style imports. Wired via extraEntries in .design-sync/config.json.
import '../frontend/src/theme/global.css';
import '@fontsource/roboto/latin-300.css';
import '@fontsource/roboto/latin-400.css';
import '@fontsource/roboto/latin-500.css';
import '@fontsource/roboto/latin-700.css';
import '@fontsource/roboto/latin-900.css';
import '@fontsource/roboto-mono/latin-400.css';
import '@fortawesome/fontawesome-free/css/fontawesome.min.css';
// solid.min.css swapped for a local woff2-only copy of its rules — the shipped
// file's .ttf fallback src has no esbuild loader here (see fa-solid.css).
import './fa-solid.css';

// Lowercase marker export (never mistaken for a component) so the module has
// a named export to merge onto the window global.
export const dsThemeLoaded = true;
