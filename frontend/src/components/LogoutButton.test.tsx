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
 * FRG-AUTH-010 — the header logout control: calls POST /api/v1/auth/logout,
 * then clears the client auth store and navigates to /login regardless of
 * the API outcome (a network hiccup shouldn't strand someone trying to sign
 * out).
 */
describe('FRG-AUTH-010: header logout control', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'authenticated', username: 'adrian' });
  });

  it('FRG-AUTH-010: logging out calls the logout endpoint, clears auth state, and redirects to /login', async () => {
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

  it('FRG-AUTH-010: a failed logout call still clears local state and redirects (never strands the user)', async () => {
    renderButton(() => {
      throw new Error('network unreachable');
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Log out' }));

    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });
});
