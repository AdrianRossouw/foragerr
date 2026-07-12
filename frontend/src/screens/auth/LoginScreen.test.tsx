import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import type { FetcherInit } from '../../api/fetcher';
import { ApiRequestError } from '../../api/fetcher';
import { useAuthStore } from '../../store/authStore';
import { LoginScreen } from './LoginScreen';

function renderLogin(route: string, resolver: (path: string, init?: FetcherInit) => unknown) {
  const { spy, fetcher } = fakeFetcher(resolver);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/queue" element={<div data-testid="queue-stub">QUEUE</div>} />
      <Route path="/" element={<div data-testid="home-stub">HOME</div>} />
    </Routes>,
    { fetcher, route },
  );
  return { spy, ...utils };
}

async function fillAndSubmit(username: string, password: string, remember = false) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Username'), username);
  await user.type(screen.getByLabelText('Password'), password);
  if (remember) {
    await user.click(screen.getByLabelText('Remember this device'));
  }
  await user.click(screen.getByRole('button', { name: /sign in/i }));
}

/**
 * FRG-AUTH-002 — the login screen: username/password/remember-me, generic
 * failure messaging (the backend never distinguishes bad-user from
 * bad-password, so the form doesn't either), and success carries the visitor
 * to wherever they were headed.
 */
describe('FRG-AUTH-002: login screen', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'checking', username: null });
  });

  it('FRG-AUTH-002: a successful login authenticates and navigates to the ?return= path', async () => {
    const { spy } = renderLogin('/login?return=%2Fqueue', () => ({ username: 'adrian' }));

    await fillAndSubmit('adrian', 'hunter2');

    expect(await screen.findByTestId('queue-stub')).toBeInTheDocument();
    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      username: 'adrian',
    });
    expect(spy).toHaveBeenCalledWith('/api/v1/auth/login', {
      method: 'POST',
      body: { username: 'adrian', password: 'hunter2', remember: false },
    });
  });

  it('FRG-AUTH-002: with no return path, a successful login goes home', async () => {
    renderLogin('/login', () => ({ username: 'adrian' }));

    await fillAndSubmit('adrian', 'hunter2');

    expect(await screen.findByTestId('home-stub')).toBeInTheDocument();
  });

  it('FRG-AUTH-002: the "remember this device" checkbox is passed through as the remember flag', async () => {
    const { spy } = renderLogin('/login', () => ({ username: 'adrian' }));

    await fillAndSubmit('adrian', 'hunter2', true);

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('/api/v1/auth/login', {
      method: 'POST',
      body: { username: 'adrian', password: 'hunter2', remember: true },
    });
  });

  it('FRG-AUTH-002: a 401 renders one generic message, never distinguishing bad username from bad password', async () => {
    renderLogin('/login', () => {
      throw new ApiRequestError(401, null, '/api/v1/auth/login');
    });

    await fillAndSubmit('adrian', 'wrong-password');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Invalid username or password.',
    );
    expect(useAuthStore.getState().status).not.toBe('authenticated');
  });

  it('FRG-AUTH-002: a non-401 failure (network/5xx) gets a distinct message from bad credentials', async () => {
    renderLogin('/login', () => {
      throw new ApiRequestError(503, null, '/api/v1/auth/login');
    });

    await fillAndSubmit('adrian', 'hunter2');

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign in. Try again.');
  });

  it('FRG-AUTH-009: a 429 tells the operator to wait, not to retry (matches the throttle contract)', async () => {
    renderLogin('/login', () => {
      throw new ApiRequestError(
        429,
        { message: 'too many failed attempts', errors: [] },
        '/api/v1/auth/login',
      );
    });

    await fillAndSubmit('adrian', 'wrong-password');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'Too many failed attempts. Please wait a moment before trying again.',
    );
    // Must NOT tell them to retry — that would contradict the backoff.
    expect(alert).not.toHaveTextContent('Try again');
    expect(useAuthStore.getState().status).not.toBe('authenticated');
  });

  it('FRG-AUTH-002: username and password inputs are properly labeled (a11y)', () => {
    renderLogin('/login', () => ({ username: 'adrian' }));

    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Remember this device')).toBeInTheDocument();
  });
});
