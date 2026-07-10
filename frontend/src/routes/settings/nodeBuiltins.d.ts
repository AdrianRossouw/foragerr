/*
 * Minimal ambient typings for the node builtins used by the FRG-UI-009
 * renderer-reuse audit test (rendererReuse.audit.test.ts). The project has no
 * @types/node (it is a browser app; tests run in jsdom) — these declare ONLY
 * the handful of fs/path/url functions the audit's module-graph walker needs.
 */

declare module 'node:fs' {
  export function readFileSync(
    path: string,
    encoding: 'utf8',
  ): string;
  export function existsSync(path: string): boolean;
  export interface Dirent {
    name: string;
    isDirectory(): boolean;
    isFile(): boolean;
  }
  export function readdirSync(
    path: string,
    options: { withFileTypes: true },
  ): Dirent[];
}

declare module 'node:path' {
  export function dirname(path: string): string;
  export function resolve(...segments: string[]): string;
  export function join(...segments: string[]): string;
  export const sep: string;
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string;
}
