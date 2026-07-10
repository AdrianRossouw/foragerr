import { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SegmentedControl } from './SegmentedControl';

/**
 * FRG-UI-003 — the shared segmented control is a WAI-ARIA radiogroup: roving
 * tabindex (only the active segment is tabbable) and ArrowLeft/Right move the
 * selection, wrapping at the ends. A tabs refactor is recorded as deferred.
 */
function Harness({ initial = 'a' }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <SegmentedControl
      ariaLabel="Test view"
      value={value}
      onChange={setValue}
      options={[
        { value: 'a', label: 'Alpha' },
        { value: 'b', label: 'Beta' },
        { value: 'c', label: 'Gamma' },
      ]}
    />
  );
}

describe('FRG-UI-003: SegmentedControl keyboard', () => {
  it('FRG-UI-003 — roving tabindex: only the active segment is in the tab order', () => {
    render(<Harness initial="b" />);
    expect(screen.getByRole('radio', { name: 'Alpha' })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('radio', { name: 'Beta' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('radio', { name: 'Gamma' })).toHaveAttribute('tabindex', '-1');
  });

  it('FRG-UI-003 — ArrowRight/ArrowLeft move the selection and wrap at the ends', async () => {
    const user = userEvent.setup();
    render(<Harness initial="a" />);

    const alpha = screen.getByRole('radio', { name: 'Alpha' });
    alpha.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Beta' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Beta' })).toHaveFocus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Gamma' })).toHaveAttribute('aria-checked', 'true');
    // Wrap forward: Gamma → Alpha.
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Alpha' })).toHaveAttribute('aria-checked', 'true');
    // Wrap backward: Alpha → Gamma.
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('radio', { name: 'Gamma' })).toHaveAttribute('aria-checked', 'true');
  });
});
