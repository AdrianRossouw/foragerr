import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route, useSearchParams } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { ApiRequestError } from '../api/fetcher';
import { useAuthStore } from '../store/authStore';
import { AuthGate } from './AuthGate';

function LoginStub() {
  const [params] = useSearchParams();
  return <div data-testid="login-stub">login return={params.get('return') ?? ''}</div>;
}

function renderApp(route: string, resolver: (path: string) => unknown) {
  const { fetcher } = fakeFetcher(resolver);
  return renderWithProviders(
    <AuthGate>
      <Routes>
        <Route path="/login" element={<LoginStub />} />
        <Route path="/queue" element={<div data-testid="protected-stub">QUEUE</div>} />
        <Route path="/" element={<div data-testid="protected-stub">HOME</div>} />
      </Routes>
    </AuthGate>,
    { fetcher, route },
  );
}

/**
 * FRG-AUTH-010 / FRG-AUTH-002 — AuthGate: the single seam deciding whether
 * protected content or the login screen is reachable, driven by the
 * boot-time GET /api/v1/auth/me.
 */
describe('AuthGate: the boot-time auth check', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'checking', username: null });
  });

  it('FRG-AUTH-010: renders the shared loading state while /auth/me is pending, never the protected route', () => {
    renderApp('/queue', () => new Promise(() => {}));
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i);
    expect(screen.queryByTestId('protected-stub')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-stub')).not.toBeInTheDocument();
  });

  it('FRG-AUTH-002: an authenticated /auth/me renders the requested protected route directly', async () => {
    renderApp('/queue', () => ({ username: 'adrian' }));
    expect(await screen.findByTestId('protected-stub')).toHaveTextContent('QUEUE');
    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      username: 'adrian',
    });
  });

  it('FRG-AUTH-010: a 401 from /auth/me redirects to /login, preserving the intended path as ?return=', async () => {
    renderApp('/queue', () => {
      throw new ApiRequestError(401, null, '/api/v1/auth/me');
    });
    expect(await screen.findByTestId('login-stub')).toHaveTextContent('return=/queue');
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  it('FRG-AUTH-010: an already-authenticated visitor landing on /login is sent to the ?return= path instead of the form', async () => {
    renderApp('/login?return=%2Fqueue', () => ({ username: 'adrian' }));
    expect(await screen.findByTestId('protected-stub')).toHaveTextContent('QUEUE');
    expect(screen.queryByTestId('login-stub')).not.toBeInTheDocument();
  });

  it('FRG-AUTH-010: an unauthenticated visitor already on /login just sees the login screen (no redirect loop)', async () => {
    renderApp('/login', () => {
      throw new ApiRequestError(401, null, '/api/v1/auth/me');
    });
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
  });

  it('FRG-AUTH-010: a same-origin-only guard falls back home for an unsafe ?return= value', async () => {
    renderApp('/login?return=%2F%2Fevil.example.com', () => ({ username: 'adrian' }));
    expect(await screen.findByTestId('protected-stub')).toHaveTextContent('HOME');
  });
});
