import { describe, it, expect } from 'vitest';
import { downloadClientKind, indexerKind } from './providerKinds';
import type { ProviderKindConfig } from './providerTypes';

/*
 * FRG-UI-009 — provider-kind CONTENT audit.
 *
 * The renderer-reuse audit (rendererReuse.audit.test.ts) is structural: it
 * proves both settings screens draw their forms with the one shared renderer.
 * It says nothing about WHAT is in the kind config — which is how the
 * download-client form could go without the priority field FRG-UI-009's
 * scenario asserts and still keep a green suite. This test pins the
 * content: EVERY provider kind exposes the row-level priority field, with the
 * same 1..50 semantics and default, so neither audit can pass vacuously.
 */

const KINDS: [string, ProviderKindConfig][] = [
  ['indexer', indexerKind],
  ['downloadclient', downloadClientKind],
];

describe('FRG-UI-009: every provider kind exposes its priority row field', () => {
  it.each(KINDS)(
    'FRG-UI-009 — the %s kind has a numeric, advanced priority row field defaulting to 25',
    (_key, kind) => {
      const priority = kind.rowFields.find((field) => field.name === 'priority');

      expect(priority, `${kind.key} rowFields must include priority`).toBeDefined();
      expect(priority!.type).toBe('number');
      // Advanced, exactly like the indexer field.
      expect(priority!.advanced).toBe(true);
      expect(priority!.required).toBe(false);
      expect(priority!.secret).toBe(false);
      // The label names its provider kind (an implementation schema may carry
      // a "Priority" of its own — SABnzbd's queue priority does).
      expect(priority!.label).toMatch(/Priority$/);
      expect(priority!.help).toContain('1 (highest) to 50 (lowest)');
      // Seeded so an add-form posts the backend's own default, not undefined.
      expect(kind.rowDefaults.priority).toBe(25);
    },
  );

  it('FRG-UI-009 — both kinds are actually covered (the audit cannot pass with an empty set)', () => {
    expect(KINDS.map(([key]) => key)).toEqual(['indexer', 'downloadclient']);
    expect(KINDS.map(([, kind]) => kind.key)).toEqual(['indexer', 'downloadclient']);
  });
});
