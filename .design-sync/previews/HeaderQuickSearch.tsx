import { HeaderQuickSearch } from 'foragerr-frontend';

/**
 * The global header quick-search box (FRG-UI-019). Its results dropdown only
 * opens on typed input (React state), which a static preview render can't
 * drive — so the honest render is the CLOSED box: search icon + placeholder,
 * on the dark header surface. Sits inside the header's 420px max-width slot.
 * (Open/results state noted as skipped in learnings/shell.md.)
 */
export const Closed = () => (
  <div style={{ maxWidth: 460 }}>
    <HeaderQuickSearch />
  </div>
);
