import { describe, it, expect } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import type { AuthCredentialsResponse } from '../../api/authHooks';
import { useAuthStore } from '../../store/authStore';
import { Security } from './Security';

/*
 * m8-keys-opds — Settings -> Security (FRG-AUTH-004/005/007). Every scenario
 * runs against an injected fake fetcher (no live backend): the web-password
 * and OPDS-password cards post to their own endpoints and clear on success
 * without any redirect (the acting session survives — FRG-AUTH-004 tail),
 * API-key rotation renders the raw key exactly once and it is unrecoverable
 * after the display-once modal closes (FRG-AUTH-007), logout-all fires its
 * request from behind a confirm, and a generic 403 re-auth failure attaches
 * to the current-password field via the shared mapApiError machinery.
 */

const CREDENTIALS: AuthCredentialsResponse = { username: 'adrian' };

interface Overrides {
  onPassword?: (init?: FetcherInit) => unknown;
  onOpdsPassword?: (init?: FetcherInit) => unknown;
  onRotate?: (init?: FetcherInit) => unknown;
  onLogoutAll?: (init?: FetcherInit) => unknown;
}

function resolver(o: Overrides = {}) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/auth/credentials') return CREDENTIALS;
    if (path === '/api/v1/auth/password' && init?.method === 'POST') {
      return o.onPassword ? o.onPassword(init) : undefined;
    }
    if (path === '/api/v1/auth/opds-password' && init?.method === 'POST') {
      return o.onOpdsPassword ? o.onOpdsPassword(init) : undefined;
    }
    if (path === '/api/v1/auth/api-key/rotate' && init?.method === 'POST') {
      return o.onRotate ? o.onRotate(init) : { api_key: 'raw-key-abc123' };
    }
    if (path === '/api/v1/auth/logout-all' && init?.method === 'POST') {
      return o.onLogoutAll ? o.onLogoutAll(init) : undefined;
    }
    throw new Error(`unexpected request: ${init?.method ?? 'GET'} ${path}`);
  };
}

describe('Settings -> Security', () => {
  it('FRG-AUTH-004: password change submits and clears form, no redirect', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver({
        onPassword: (init) => {
          const body = init?.body as {
            current_password: string;
            new_password: string;
          };
          expect(body).toEqual({
            current_password: 'old-pass',
            new_password: 'new-pass-123',
          });
          return undefined;
        },
      }),
    );
    renderWithProviders(<Security />, { fetcher, route: '/settings/security' });

    await screen.findByText('adrian');
    await user.type(screen.getByLabelText('Current password'), 'old-pass');
    await user.type(screen.getByLabelText('New password'), 'new-pass-123');
    await user.type(
      screen.getByLabelText('Confirm new password'),
      'new-pass-123',
    );
    await user.click(screen.getByRole('button', { name: 'Change Password' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/auth/password',
        expect.objectContaining({ method: 'POST' }),
      ),
    );

    // Cleared on success.
    await waitFor(() =>
      expect(screen.getByLabelText('Current password')).toHaveValue(''),
    );
    expect(screen.getByLabelText('New password')).toHaveValue('');
    expect(screen.getByLabelText('Confirm new password')).toHaveValue('');
    expect(screen.getByRole('status')).toHaveTextContent('Password changed.');

    // The page itself is still rendered — no redirect fired off the acting
    // session (which the backend contract preserves for this endpoint).
    expect(screen.getByText('Settings — Security')).toBeInTheDocument();
  });

  it('FRG-AUTH-005: OPDS password form posts to opds-password endpoint', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver({
        onOpdsPassword: (init) => {
          const body = init?.body as {
            current_password: string;
            new_password: string;
          };
          expect(body).toEqual({
            current_password: 'admin-pass',
            new_password: 'opds-pass-123',
          });
          return undefined;
        },
      }),
    );
    renderWithProviders(<Security />, { fetcher, route: '/settings/security' });

    await screen.findByText('adrian');
    await user.type(
      screen.getByLabelText('Current admin password'),
      'admin-pass',
    );
    await user.type(
      screen.getByLabelText('New OPDS password'),
      'opds-pass-123',
    );
    await user.type(
      screen.getByLabelText('Confirm new OPDS password'),
      'opds-pass-123',
    );
    await user.click(
      screen.getByRole('button', { name: 'Change OPDS Password' }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/auth/opds-password',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    expect(
      await screen.findByText(/OPDS password changed/),
    ).toBeInTheDocument();
  });

  it('FRG-AUTH-007: rotated key renders once and is not recoverable after modal close', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    const { client } = renderWithProviders(<Security />, {
      fetcher,
      route: '/settings/security',
    });

    await screen.findByText('adrian');
    await user.click(screen.getByRole('button', { name: 'Rotate API Key' }));

    const confirmDialog = await screen.findByRole('dialog', {
      name: 'Rotate API key',
    });
    await user.type(
      within(confirmDialog).getByLabelText('Current password'),
      'admin-pass',
    );
    await user.click(
      within(confirmDialog).getByRole('button', { name: 'Rotate' }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/auth/api-key/rotate',
        expect.objectContaining({
          method: 'POST',
          body: { current_password: 'admin-pass' },
        }),
      ),
    );

    // The raw key renders exactly once, in the display-once modal.
    const keyModal = await screen.findByRole('dialog', { name: 'New API key' });
    expect(
      within(keyModal).getByLabelText('New API key'),
    ).toHaveValue('raw-key-abc123');

    await user.click(within(keyModal).getByRole('button', { name: 'Done' }));

    // Gone from the DOM...
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: 'New API key' }),
      ).not.toBeInTheDocument(),
    );
    expect(document.body.innerHTML).not.toMatch(/raw-key-abc123/);
    // ...and never lived anywhere but component state — no query cache entry
    // carries it, and no persistent store was ever written.
    const cachedValues = client
      .getQueryCache()
      .getAll()
      .map((q) => JSON.stringify(q.state.data));
    expect(cachedValues.join('')).not.toMatch(/raw-key-abc123/);
    // The MutationCache is the place React Query actually retains a mutation's
    // data + variables — assert the raw key AND the submitted admin password are
    // both gone from it (the gate-finding fix: gcTime:0 + .reset()).
    const mutationState = client
      .getMutationCache()
      .getAll()
      .map((m) => JSON.stringify(m.state));
    expect(mutationState.join('')).not.toMatch(/raw-key-abc123/);
    expect(mutationState.join('')).not.toMatch(/admin-pass/);
    expect(Object.keys(window.localStorage)).toHaveLength(0);

    // The rotate trigger is back to its normal state — the only way to see a
    // key again is a brand-new rotation, not a re-opened stale modal.
    expect(
      screen.getByRole('button', { name: 'Rotate API Key' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('dialog', { name: 'New API key' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-AUTH-004: logout-all fires the request, clears auth state, and redirects to /login', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    useAuthStore.setState({ status: 'authenticated', username: 'adrian' });
    renderWithProviders(
      <Routes>
        <Route path="/settings/security" element={<Security />} />
        <Route
          path="/login"
          element={<div data-testid="login-stub">LOGIN</div>}
        />
      </Routes>,
      { fetcher, route: '/settings/security' },
    );

    await screen.findByText('adrian');
    await user.click(
      screen.getByRole('button', { name: 'Log Out All Devices' }),
    );

    const dialog = await screen.findByRole('dialog', {
      name: 'Log out all devices',
    });
    await user.click(
      within(dialog).getByRole('button', { name: 'Log Out All Devices' }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/auth/logout-all',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    // The shell is actually torn down: auth state flips and the SPA lands on
    // the login screen (not just the request fired).
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
    await waitFor(() =>
      expect(useAuthStore.getState().status).toBe('unauthenticated'),
    );
  });

  it('a 403 re-auth failure renders the generic current-password error (FRG-AUTH-004)', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        onPassword: () => {
          throw new ApiRequestError(
            403,
            { message: 'Forbidden', errors: [] },
            '/api/v1/auth/password',
          );
        },
      }),
    );
    renderWithProviders(<Security />, { fetcher, route: '/settings/security' });

    await screen.findByText('adrian');
    await user.type(screen.getByLabelText('Current password'), 'wrong-pass');
    await user.type(screen.getByLabelText('New password'), 'new-pass-123');
    await user.type(
      screen.getByLabelText('Confirm new password'),
      'new-pass-123',
    );
    await user.click(screen.getByRole('button', { name: 'Change Password' }));

    const card = screen.getByTestId('web-password-card');
    await waitFor(() =>
      expect(within(card).getByRole('alert')).toHaveTextContent(
        'Current password is incorrect.',
      ),
    );
    // Not cleared on error — the operator can correct it in place.
    expect(screen.getByLabelText('Current password')).toHaveValue(
      'wrong-pass',
    );
  });
});
