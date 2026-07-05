import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// Ensure the DOM is torn down between tests so token/computed-style assertions and
// the WebSocketBridge connection-state tests never leak state across cases.
afterEach(() => {
  cleanup();
});
