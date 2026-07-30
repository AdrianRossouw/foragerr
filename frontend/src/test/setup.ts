import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import { resetViewport } from './viewport';

// Ensure the DOM is torn down between tests so token/computed-style assertions and
// the WebSocketBridge connection-state tests never leak state across cases.
afterEach(() => {
  cleanup();
  // A stubbed viewport is global state: without this, one narrow-viewport test
  // would put every later test in the file into compact mode.
  resetViewport();
});
