import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { useAuthStore } from '../store/authStore';
import { LogoutButton } from './LogoutButton';

function renderButton(resolver: () => unknown = () => undefined) {
  const { spy, fetcher } = fakeFetcher(resolver);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<LogoutButton />} />
      <Route path="/login" element={<div data-testid="login-stub">LOGIN</div>} />
    </Routes>,
    { fetcher, route: '/' },
  );
  return { spy, ...utils };
}

/**
 * FRG-AUTH-004 — the header logout control treats logout as complete ONLY when
 * the server confirms it: a confirmed logout clears the client and returns to
 * /login; a FAILED logout keeps the session (the HttpOnly cookie may still be
 * live) and offers a retry rather than falsely presenting a signed-out state.
 * FRG-AUTH-010 — the control calls POST /api/v1/auth/logout.
 */
describe('FRG-AUTH-004: header logout control', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'authenticated', username: 'adrian' });
  });

  it('FRG-AUTH-004 / FRG-AUTH-010: a confirmed logout calls the endpoint, clears auth state, and redirects to /login', async () => {
    const { spy } = renderButton(() => undefined);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Log out' }));

    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('/api/v1/auth/logout', { method: 'POST' });
    await waitFor(() =>
      expect(useAuthStore.getState()).toMatchObject({
        status: 'unauthenticated',
        username: null,
      }),
    );
  });

  it('FRG-AUTH-004: a failed logout keeps the session (no clear, no redirect) and shows a retryable error', async () => {
    renderButton(() => {
      throw new Error('logout refused');
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Log out' }));

    // Retryable error is surfaced accessibly...
    expect(await screen.findByRole('alert')).toHaveTextContent(/try again/i);
    // ...and the operator is NOT stranded as signed-out: still authenticated,
    // still on the app view (no navigation to the login stub).
    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(screen.queryByTestId('login-stub')).not.toBeInTheDocument();
  });

  it('FRG-AUTH-004: retrying after a failed logout completes normally', async () => {
    let calls = 0;
    renderButton(() => {
      calls += 1;
      if (calls === 1) throw new Error('logout refused');
      return undefined;
    });
    const user = userEvent.setup();
    const button = screen.getByRole('button', { name: 'Log out' });

    await user.click(button); // fails
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe('authenticated');

    await user.click(button); // retry succeeds
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
    await waitFor(() =>
      expect(useAuthStore.getState().status).toBe('unauthenticated'),
    );
  });
});
