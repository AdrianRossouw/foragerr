import { GlobalBanner, PreviewData } from 'foragerr-frontend';

/**
 * The banner raises itself off the sources cache — seed one expired source.
 * (Propless component: with no expired session it renders nothing by design.)
 */
export const SessionExpired = () => (
  <PreviewData
    responses={{
      sources: [
        {
          id: 1,
          type: 'humble',
          name: 'Humble Bundle',
          connection_state: 'expired',
          auto_sync: false,
          last_sync_status: null,
          settings: {},
        },
      ],
    }}
  >
    <GlobalBanner />
  </PreviewData>
);
