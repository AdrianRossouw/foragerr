import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReasonsPopover } from './ReasonsPopover';

/**
 * FRG-UI-014 — Shared reasons popover: the decision-overlay primitive that both
 * the manual-import and interactive-search overlays render. Reasons stay hidden
 * until the chip is activated, then appear VERBATIM and in the exact order they
 * were passed (the endpoint's order — never re-sorted), under the caller's
 * `ft-*` list testid.
 */
describe('FRG-UI-014: shared ReasonsPopover', () => {
  const REASONS = ['No series match for parsed title', 'Unmapped issue number'];

  it('FRG-UI-014 — hides reasons until the chip is activated, then shows them verbatim and in order', async () => {
    const user = userEvent.setup();
    render(
      <ReasonsPopover
        reasons={REASONS}
        label="mystery.cbr — show reasons"
        chipClassName="chip"
        chipContent={<>! Blocked</>}
        listTestId="ft-manual-rejections-mystery.cbr"
      />,
    );

    // Nothing rendered until the trigger is clicked.
    expect(screen.queryByText('No series match for parsed title')).not.toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'mystery.cbr — show reasons' }),
    );

    // The list carries the caller's ft-* testid and the verbatim reasons, in order.
    const list = screen.getByTestId('ft-manual-rejections-mystery.cbr');
    const items = within(list).getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual(REASONS);
  });

  it('FRG-UI-014 — renders the supplied chip content as the popover trigger', () => {
    render(
      <ReasonsPopover
        reasons={['Below minimum size']}
        label="Rejected — show reasons"
        chipClassName="chip chipRejected"
        chipContent={<>! Rejected</>}
        listTestId="ft-rejections-guid-1"
      />,
    );
    expect(
      screen.getByRole('button', { name: 'Rejected — show reasons' }),
    ).toHaveTextContent('! Rejected');
  });
});
