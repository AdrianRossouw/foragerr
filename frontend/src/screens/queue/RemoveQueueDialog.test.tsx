import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/renderWithProviders';
import { toQueueItem } from '../../api/queue';
import { mockQueueRecord } from '../../test/mockData';
import { RemoveQueueDialog } from './RemoveQueueDialog';

/*
 * FRG-UI-006 — the remove-queue dialog builds its display name with `!= null`
 * (matching the queue table), so a legitimate issue "#0" is never dropped by a
 * falsy-value check.
 */
describe('FRG-UI-006: remove-queue dialog display name', () => {
  it('FRG-UI-006 — issue "#0" is shown, not dropped as falsy', () => {
    const item = toQueueItem(
      mockQueueRecord({
        id: 42,
        issue: { id: 1, issueNumber: '0', title: 'Special Zero' },
      }),
    );

    renderWithProviders(<RemoveQueueDialog item={item} onClose={() => {}} />);

    // The <strong> in the confirmation body is exactly the display name.
    expect(screen.getByText('Saga #0')).toBeInTheDocument();
  });
});
