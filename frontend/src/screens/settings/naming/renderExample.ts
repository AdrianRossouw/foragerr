/*
 * Client-side LIVE-EXAMPLE render mirror (FRG-UI-012, design decision 11).
 *
 * This is display sugar ONLY: it recomputes the "Example:" line under a template
 * input as the operator types, so they get instant feedback without a save
 * round-trip. The AUTHORITATIVE render is always server-side — the per-series
 * rename preview (GET /api/v1/rename) and the import pipeline both call the
 * Python `foragerr.naming` engine, never this. This mirror deliberately
 * implements only the rules that shape the default token vocabulary the UI
 * exposes (token substitution, `:pad` zero-padding, token-name case control,
 * optional-group dropping, and the file-name illegal-char + whitespace policy)
 * and is fixture-tested against the backend's own expected outputs
 * (renderExample.test.ts) so the two never drift for those defaults.
 *
 * The token vocabulary is NOT hardcoded here: the caller passes the alias table
 * fetched from GET /api/v1/config/naming/tokens (the one shared definition), so
 * there is no duplicate token list in the frontend.
 */

/** Canonical field key -> its string value for the example issue (or null/absent). */
export type ExampleFields = Record<string, string | null | undefined>;

/** Casefolded token name -> canonical field key (from the backend token table). */
export type TokenAliases = Record<string, string>;

// Mirrors foragerr.naming: {Token} or {Token:pad}, and [ optional group ].
const TOKEN_RE = /\{([^{}:]+)(?::([^{}]*))?\}/g;
const GROUP_RE = /\[([^[\]]*)\]/g;
const WS_RE = /[ \t]+/g;

// Illegal filename characters, mirroring naming._ILLEGAL_RE. Kept as a
// char-set + code check (rather than a regex with literal control bytes) so the
// source stays ASCII-clean: the visible punctuation set plus C0 controls + DEL.
const ILLEGAL_PUNCT = new Set(['<', '>', ':', '"', '/', '\\', '|', '?', '*']);

function isIllegalChar(ch: string): boolean {
  if (ILLEGAL_PUNCT.has(ch)) return true;
  const code = ch.codePointAt(0) ?? 0;
  return code <= 0x1f || code === 0x7f;
}

function replaceIllegal(text: string): string {
  let out = '';
  for (const ch of text) out += isIllegalChar(ch) ? ' ' : ch;
  return out;
}

function canonical(name: string): string {
  return name.trim().split(/\s+/).join(' ').toLowerCase();
}

/** Token-name case controls output case (naming._apply_case). */
function applyCase(rawName: string, value: string): string {
  if (!value) return value;
  const letters = [...rawName].filter((c) => /[a-z]/i.test(c));
  if (letters.length === 0) return value;
  if (letters.every((c) => c === c.toUpperCase())) return value.toUpperCase();
  if (letters.every((c) => c === c.toLowerCase())) return value.toLowerCase();
  return value;
}

/** Zero-pad the integer part decimal-safely (naming._apply_pad): 15.5 -> 015.5. */
function applyPad(value: string, pad: string): string {
  const width = pad.length;
  if (width === 0) return value;
  const neg = value.startsWith('-');
  const core = neg ? value.slice(1) : value;
  const dot = core.indexOf('.');
  const intPart = dot === -1 ? core : core.slice(0, dot);
  const frac = dot === -1 ? '' : core.slice(dot + 1);
  if (!/^\d+$/.test(intPart)) return value; // named/suffix issue, no numeric part
  const padded = intPart.padStart(width, '0');
  const result = dot === -1 ? padded : `${padded}.${frac}`;
  return neg ? `-${result}` : result;
}

function renderSegment(
  text: string,
  fields: ExampleFields,
  aliases: TokenAliases,
  empties: boolean[],
): string {
  return text.replace(TOKEN_RE, (_match, name: string, pad: string | undefined) => {
    const key = aliases[canonical(name)];
    const raw = key !== undefined ? fields[key] : undefined;
    let val = raw == null ? '' : String(raw);
    if (pad !== undefined && val) val = applyPad(val, pad);
    val = applyCase(name, val);
    empties.push(val === '');
    return val;
  });
}

/**
 * Render a template against the example fields (tokens + optional groups),
 * mirroring naming.render. A bracketed span that contains at least one token and
 * whose every token resolved empty is dropped entirely; a bracketed span with no
 * tokens is literal text and is kept.
 */
export function renderTemplate(
  template: string,
  fields: ExampleFields,
  aliases: TokenAliases,
): string {
  const out: string[] = [];
  let pos = 0;
  GROUP_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = GROUP_RE.exec(template)) !== null) {
    out.push(renderSegment(template.slice(pos, m.index), fields, aliases, []));
    const innerEmpties: boolean[] = [];
    const inner = renderSegment(m[1], fields, aliases, innerEmpties);
    if (innerEmpties.length > 0 && innerEmpties.every(Boolean)) {
      // bracketed span with tokens, all empty -> drop it entirely
    } else {
      out.push(`[${inner}]`);
    }
    pos = m.index + m[0].length;
  }
  out.push(renderSegment(template.slice(pos), fields, aliases, []));
  return out.join('');
}

function stripSpaceDot(text: string): string {
  return text.replace(/^[ .]+/, '').replace(/[ .]+$/, '');
}

// Windows/DOS reserved device names, mirroring paths._RESERVED_NAMES — reserved
// with or without an extension, so the check is against the segment before the
// first dot.
const RESERVED_NAMES = new Set<string>([
  'CON',
  'PRN',
  'AUX',
  'NUL',
  ...Array.from({ length: 9 }, (_, i) => `COM${i + 1}`),
  ...Array.from({ length: 9 }, (_, i) => `LPT${i + 1}`),
]);

/**
 * Reduce one string to a single filesystem-safe path segment, mirroring the
 * backend's authoritative `foragerr.security.paths.safe_path_component`
 * (FRG-SEC-004): path separators and control characters become spaces,
 * whitespace runs collapse, leading/trailing spaces-and-dots are stripped, an
 * empty result falls back to "untitled", and a Windows reserved device name is
 * de-reserved with a leading underscore. Folder rendering delegates per-segment
 * safety to this (via `safe_join` server-side), so the live example must too.
 */
function safePathComponent(raw: string, fallback = 'untitled'): string {
  let text = raw.replace(/[/\\]/g, ' ');
  let controlStripped = '';
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    controlStripped += code <= 0x1f || code === 0x7f ? ' ' : ch;
  }
  text = controlStripped.trim().split(/\s+/).join(' ');
  text = stripSpaceDot(text);
  if (!text) text = fallback;
  const stem = text.split('.')[0].toUpperCase();
  if (RESERVED_NAMES.has(stem)) text = `_${text}`;
  return text;
}

/**
 * Render a FOLDER template's live example, mirroring the backend pipeline
 * `render_folder_segments` + `safe_join`'s per-segment `safe_path_component`
 * (never the file-name policy): render the template, collapse [ \t] runs, split
 * on "/", drop whitespace-empty segments, sanitize each surviving segment, and
 * rejoin with "/". Crucially there is NO file-style whole-string trailing-dot
 * strip — the backend strips per segment inside `safe_path_component`, so a
 * template like "{Series Title}." yields the sanitized segment, not the file
 * body's stripped form.
 */
function renderFolderExample(
  template: string,
  fields: ExampleFields,
  aliases: TokenAliases,
): string {
  const rendered = renderTemplate(template, fields, aliases).replace(WS_RE, ' ');
  return rendered
    .split('/')
    .map((seg) => seg.trim())
    .filter((seg) => seg.length > 0)
    .map((seg) => safePathComponent(seg))
    .join('/');
}

export interface RenderExampleOptions {
  /** File-name rendering applies the illegal-char policy + appends the ext. */
  isFile: boolean;
  /** Whether illegal filename characters are replaced (file rendering only). */
  replaceIllegal?: boolean;
  /** Representative extension for the file example (e.g. ".cbz"). */
  ext?: string;
}

/**
 * Render the live "Example:" string for one template. For file rendering this
 * mirrors naming._render_body + render_filename's ext handling (illegal-char
 * replacement, whitespace collapse, trailing space/dot strip); byte-length
 * truncation is intentionally omitted — it never affects the short default
 * example and the server remains the authority for real names.
 */
export function renderExample(
  template: string,
  fields: ExampleFields,
  aliases: TokenAliases,
  opts: RenderExampleOptions,
): string {
  // Folder rendering has different backend semantics (per-segment
  // safe_path_component, NOT the file illegal-char + trailing-dot policy).
  if (!opts.isFile) {
    return renderFolderExample(template, fields, aliases);
  }
  let body = renderTemplate(template, fields, aliases);
  if (opts.replaceIllegal ?? true) {
    body = replaceIllegal(body);
  }
  body = stripSpaceDot(body.replace(WS_RE, ' ').trim());
  if (opts.ext) body += opts.ext;
  return body;
}
