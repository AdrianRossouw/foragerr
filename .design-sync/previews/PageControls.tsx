import { PageControls } from 'foragerr-frontend';

/** A mid-range page, prev/next both enabled. */
export const MiddlePage = () => (
  <PageControls page={3} totalRecords={97} pageSize={20} onPageChange={() => {}} />
);

/** First page — Prev disabled — and last page — Next disabled. */
export const Boundaries = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
    <PageControls page={1} totalRecords={53} pageSize={20} onPageChange={() => {}} />
    <PageControls page={3} totalRecords={53} pageSize={20} onPageChange={() => {}} />
  </div>
);

/** Empty result set renders nothing — shown labeled so the blank cell reads as
 * intentional rather than a broken capture. */
export const EmptyRendersNothing = () => (
  <div>
    <span style={{ color: 'var(--color-text-muted, #9a9a9a)', fontSize: 13 }}>
      No results — PageControls renders null below:
    </span>
    <PageControls page={1} totalRecords={0} pageSize={20} onPageChange={() => {}} />
  </div>
);
