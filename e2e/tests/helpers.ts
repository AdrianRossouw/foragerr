import type { APIRequestContext } from '@playwright/test';

/** Enabled providers pointing at mockhub (resolved inside the compose network).
 *  Idempotent: safe to call again on a serial-group retry. */
export async function createProviders(api: APIRequestContext): Promise<void> {
  const indexers = await (await api.get('/api/v1/indexer')).json();
  const names = new Set((indexers as any[]).map((i) => i.name));

  if (!names.has('mock-newznab')) {
    await expectOk(
      api.post('/api/v1/indexer', {
        data: {
          name: 'mock-newznab',
          implementation: 'newznab',
          settings: {
            base_url: 'http://mockhub:8080/newznab',
            api_key: 'e2e-example',
            categories: [7030],
          },
          enabled: true,
        },
      }),
      'create newznab indexer',
    );
  }

  if (!names.has('mock-getcomics')) {
    await expectOk(
      api.post('/api/v1/indexer', {
        data: {
          name: 'mock-getcomics',
          implementation: 'getcomics',
          settings: {
            base_url: 'https://getcomics.org',
            min_interval_seconds: 1,
            max_pages: 1,
          },
          enabled: true,
        },
      }),
      'create getcomics indexer',
    );
  }

  const clients = await (await api.get('/api/v1/downloadclient')).json();
  if (!(clients as any[]).some((c) => c.name === 'builtin-ddl')) {
    await expectOk(
      api.post('/api/v1/downloadclient', {
        data: {
          name: 'builtin-ddl',
          implementation: 'ddl',
          settings: {
            host_priority: 'main,mirror,pixeldrain,mediafire,mega',
            prefer_upscaled: true,
          },
          enabled: true,
        },
      }),
      'create ddl download client',
    );
  }
}

async function expectOk(p: ReturnType<APIRequestContext['post']>, what: string) {
  const res = await p;
  if (!res.ok()) {
    throw new Error(`${what} failed: HTTP ${res.status()} ${await res.text()}`);
  }
  return res;
}

/** Poll ``fn`` until it returns truthy or ``timeoutMs`` elapses. */
export async function until<T>(
  fn: () => Promise<T | undefined | false>,
  { timeoutMs = 90_000, intervalMs = 2_000, label = 'condition' } = {},
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: unknown;
  while (Date.now() < deadline) {
    try {
      const v = await fn();
      if (v) return v as T;
    } catch (err) {
      last = err;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`timed out waiting for ${label}${last ? `: ${String(last)}` : ''}`);
}

/** Nudge the completed-download → import machinery (event-triggered, but this
 *  makes the hermetic run deterministic without waiting on the ~60s poll). */
export async function nudgeImport(api: APIRequestContext): Promise<void> {
  await api.post('/api/v1/command', { data: { name: 'track-downloads' } });
  await api.post('/api/v1/command', { data: { name: 'process-imports' } });
}
