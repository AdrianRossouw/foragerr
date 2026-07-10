import { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Modal } from './Modal';

/**
 * FRG-UI-004 — shared Modal a11y: focus-on-open (first focusable), a Tab focus
 * trap, focus-restore-on-close, plus the pre-existing Escape/backdrop close.
 */
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && (
        <Modal
          title="Demo"
          label="Demo dialog"
          onClose={() => setOpen(false)}
          footer={
            <button type="button" onClick={() => setOpen(false)}>
              Done
            </button>
          }
        >
          <input aria-label="First field" />
          <input aria-label="Second field" />
        </Modal>
      )}
    </div>
  );
}

describe('FRG-UI-004: Modal focus management', () => {
  it('FRG-UI-004 — opening moves focus into the panel; Escape closes and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const opener = screen.getByRole('button', { name: 'Open' });
    opener.focus();
    await user.click(opener);

    // First focusable (the Close button) receives focus on open.
    const dialog = screen.getByRole('dialog', { name: 'Demo dialog' });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Demo dialog' })).not.toBeInTheDocument();
    // Focus is restored to the element that opened the dialog.
    expect(opener).toHaveFocus();
  });

  it('FRG-UI-004 — Tab from the last focusable wraps back to the first (focus trap)', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Open' }));

    const done = screen.getByRole('button', { name: 'Done' });
    done.focus();
    await user.tab();
    const dialog = screen.getByRole('dialog', { name: 'Demo dialog' });
    // Focus stays trapped inside the panel (wraps to the first focusable).
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
  });
});
