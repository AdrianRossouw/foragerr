import { describe, it, expect } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { createQueryClient } from '../queryClient';
import { makeFakeSocketFactory } from '../test/fakeSocket';
import { setViewportWidth } from '../test/viewport';
import { COMPACT_CROSSOVER_PX } from '../theme/layout';
import { AppShell } from './AppShell';

/**
 * FRG-UI-049 — the shell's chrome below the compact crossover: no fixed sidebar
 * column, a labelled header toggle, and a keyboard-operable off-canvas drawer.
 * At or above the crossover FRG-UI-023's frame is unchanged and no toggle exists.
 */

const WIDE = COMPACT_CROSSOVER_PX + 100;
const NARROW = COMPACT_CROSSOVER_PX - 300;

function renderShell(path = '/queue') {
  const { factory } = makeFakeSocketFactory();
  return renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell socketFactory={factory} />}>
          <Route path="/" element={<div>HOME BODY</div>} />
          <Route path="/queue" element={<div>ROUTE BODY</div>} />
          <Route path="/wanted" element={<div>WANTED BODY</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
    { withRouter: false, client: createQueryClient() },
  );
}

describe('FRG-UI-049: responsive application chrome', () => {
  it('FRG-UI-049 — a wide viewport renders the persistent sidebar column and no nav toggle', () => {
    setViewportWidth(WIDE);
    renderShell();

    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-status')).toBeInTheDocument();
    expect(screen.queryByTestId('nav-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument();
    // The frame still spans one grid with the sidebar's own column.
    const shell = screen.getByText('ROUTE BODY').closest('[data-compact]');
    expect(shell).toHaveAttribute('data-compact', 'false');
  });

  it('FRG-UI-049 — below the crossover the sidebar holds no column and a labelled toggle appears', () => {
    setViewportWidth(NARROW);
    renderShell();

    const toggle = screen.getByTestId('nav-toggle');
    expect(toggle).toHaveAccessibleName('Open navigation');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    // Nothing of the nav occupies the frame until it is asked for.
    expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument();
    expect(screen.getByText('ROUTE BODY')).toBeInTheDocument();
    expect(screen.getByText('ROUTE BODY').closest('[data-compact]')).toHaveAttribute(
      'data-compact',
      'true',
    );
  });

  it('FRG-UI-049 — opening the drawer from the keyboard moves focus into it, and Escape closes it and returns focus to the toggle', async () => {
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    const toggle = screen.getByTestId('nav-toggle');
    toggle.focus();
    await user.keyboard('{Enter}');

    const drawer = await screen.findByTestId('nav-drawer');
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // Focus is inside the drawer, not left behind on the toggle.
    expect(drawer).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('nav-toggle')).toHaveFocus();
    expect(screen.getByTestId('nav-toggle')).toHaveAttribute('aria-expanded', 'false');
  });

  it('FRG-UI-049 — the open drawer claims modality and contains focus with it', async () => {
    // `aria-modal` without containment is worse than neither: assistive
    // technology hides the outside world while Tab still walks into it, behind an
    // opaque backdrop. The backdrop already intercepts every click, so the rest
    // of the frame is inert while the drawer is open.
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    const drawer = await screen.findByTestId('nav-drawer');
    expect(drawer).toHaveAttribute('role', 'dialog');
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    expect(drawer).toHaveAccessibleName('Navigation');

    // Nothing focusable is left reachable outside the drawer: every candidate
    // either lives in it or sits inside an inert subtree.
    const escapees = Array.from(
      document.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex]',
      ),
    ).filter(
      (el) => !drawer.contains(el) && el.closest('[inert]') === null,
    );
    expect(escapees.map((el) => el.outerHTML.slice(0, 60))).toEqual([]);

    // The toggle is one of those unreachable elements, so it names the only
    // thing it can do: a "Close navigation" name would advertise an action
    // nothing can reach, while aria-expanded still reports the drawer's state.
    const toggle = screen.getByTestId('nav-toggle');
    expect(toggle).toHaveAccessibleName('Open navigation');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle.closest('[inert]')).not.toBeNull();

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument(),
    );
    // Containment is released with the drawer, or the app would be dead.
    expect(document.querySelectorAll('[inert]')).toHaveLength(0);
  });

  it('FRG-UI-049 — focus enters the drawer at the first nav item, not the brand link home', async () => {
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    await screen.findByTestId('nav-drawer');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(nav).toContainElement(document.activeElement as HTMLElement);
    expect(document.activeElement).toHaveAccessibleName(/Comics/);
  });

  it('FRG-UI-049 — widening past the crossover with the drawer open moves focus into the persistent nav', async () => {
    // The drawer unmounts without a dismissal, so focus inside it would fall to
    // the document body and restart the tab order at the skip link.
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    await screen.findByTestId('nav-drawer');

    act(() => setViewportWidth(WIDE));
    await waitFor(() =>
      expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument(),
    );
    expect(document.activeElement).not.toBe(document.body);
    expect(
      screen.getByRole('navigation', { name: 'Primary' }),
    ).toContainElement(document.activeElement as HTMLElement);
    // Containment is gated on the drawer's own render condition, so a frame with
    // no drawer in it can never be a frame with the whole app inert.
    expect(document.querySelectorAll('[inert]')).toHaveLength(0);
  });

  it('FRG-UI-049 — the backdrop dismisses the drawer and restores focus to the toggle', async () => {
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    await screen.findByTestId('nav-drawer');
    await user.click(screen.getByTestId('nav-backdrop'));

    await waitFor(() =>
      expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('nav-toggle')).toHaveFocus();
  });

  it('FRG-UI-049 — choosing a nav item navigates and closes the drawer', async () => {
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    await screen.findByTestId('nav-drawer');
    await user.click(screen.getByRole('link', { name: /Wanted/ }));

    expect(await screen.findByText('WANTED BODY')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-049 — widening past the crossover restores the persistent column and retires the toggle', async () => {
    setViewportWidth(NARROW);
    renderShell();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('nav-toggle'));
    await screen.findByTestId('nav-drawer');

    act(() => setViewportWidth(WIDE));
    await waitFor(() =>
      expect(screen.queryByTestId('nav-toggle')).not.toBeInTheDocument(),
    );
    expect(screen.queryByTestId('nav-drawer')).not.toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
  });
});
