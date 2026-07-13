import { FullPageLoading } from 'foragerr-frontend';

/** Full-page loading state shown while the boot-time auth check is pending. */
export const Default = () => (
  <div style={{ height: 240, position: 'relative' }}>
    <FullPageLoading />
  </div>
);
