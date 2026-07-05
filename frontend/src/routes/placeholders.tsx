import { useParams } from 'react-router-dom';
import { Toolbar } from '../components/Toolbar';
import { useSeriesList } from '../api/hooks';
import { AccentSwatch } from '../components/AccentSwatch';

/*
 * PLACEHOLDER route components. These prove the architecture (shell + routing +
 * token consumption + a real ['series'] query) WITHOUT implementing the real
 * screens. The full screens (FRG-UI-003..009) replace these in change 7 proper,
 * once the API response contracts are final.
 */

function PlaceholderBody({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: 'var(--spacing-lg)' }}>{children}</div>
  );
}

/** Library index placeholder — deliberately mounts the ['series'] query. */
export function LibraryIndexPlaceholder() {
  const { data, isLoading, isError } = useSeriesList();
  return (
    <>
      <Toolbar title="Library" actions={<AccentSwatch label="Add New" />} />
      <PlaceholderBody>
        <h1>Series (placeholder)</h1>
        {isLoading && <p>Loading series…</p>}
        {isError && <p>Could not load series.</p>}
        {data && <p data-testid="series-count">{data.length} series</p>}
      </PlaceholderBody>
    </>
  );
}

export function SeriesDetailPlaceholder() {
  const { id } = useParams();
  return (
    <>
      <Toolbar title="Series Detail" />
      <PlaceholderBody>
        <h1>Series {id} (placeholder)</h1>
      </PlaceholderBody>
    </>
  );
}

export function AddSeriesPlaceholder() {
  return (
    <>
      <Toolbar title="Add New" />
      <PlaceholderBody>
        <h1>Add Series (placeholder)</h1>
      </PlaceholderBody>
    </>
  );
}

export function QueuePlaceholder() {
  return (
    <>
      <Toolbar title="Queue" />
      <PlaceholderBody>
        <h1>Queue (placeholder)</h1>
      </PlaceholderBody>
    </>
  );
}

export function SettingsPlaceholder({ area }: { area: string }) {
  return (
    <>
      <Toolbar title={`Settings — ${area}`} />
      <PlaceholderBody>
        <h1>{area} settings (placeholder)</h1>
      </PlaceholderBody>
    </>
  );
}
