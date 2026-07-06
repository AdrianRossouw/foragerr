import { useId, useMemo } from 'react';
import { Popover } from '../../../components/Popover';
import type { NamingTokens } from '../../../api/types';
import {
  renderExample,
  type ExampleFields,
  type TokenAliases,
} from './renderExample';
import { tokenGroups } from './namingTokens';
import styles from './MediaManagement.module.css';

/*
 * Bespoke naming-template field (FRG-UI-012, design decision 11): a monospace
 * template input the schema-form renderer cannot express, carrying two things
 * unique to naming — a LIVE example line that recomputes client-side as the
 * operator types (from the one shared token vocabulary, no save round-trip) and
 * a `?` token-help popover rendering that same vocabulary.
 */

interface TemplateFieldProps {
  label: string;
  /** Backend settings name (e.g. "file_naming_template") — for the error map. */
  name: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  /** Sample issue field values driving the live example. */
  exampleFields: ExampleFields;
  tokens: NamingTokens | undefined;
  /** The token vocabulary is still loading (no example can be rendered yet). */
  tokensPending: boolean;
  /** The token vocabulary failed to load (the example is unavailable). */
  tokensError: boolean;
  /** File templates apply the illegal-char policy + a representative extension. */
  isFile: boolean;
  replaceIllegal: boolean;
  /** Whether renaming is enabled — a disabled renamer keeps original names. */
  renameEnabled: boolean;
}

export function TemplateField({
  label,
  name,
  value,
  onChange,
  error,
  exampleFields,
  tokens,
  tokensPending,
  tokensError,
  isFile,
  replaceIllegal,
  renameEnabled,
}: TemplateFieldProps) {
  const id = useId();
  const aliases: TokenAliases = tokens?.aliases ?? {};
  const groups = useMemo(() => tokenGroups(tokens), [tokens]);
  // The default template shipped by the tokens endpoint (design decision 11):
  // used for the "Reset to default" affordance so nothing is hardcoded here.
  const defaultTemplate = tokens?.defaults?.[name];
  // Only render an example once the token vocabulary has resolved: with an empty
  // alias table every token collapses to '', producing garbage like "().cbz".
  const example =
    tokens !== undefined
      ? renderExample(value, exampleFields, aliases, {
          isFile,
          replaceIllegal,
          ext: isFile ? '.cbz' : undefined,
        })
      : '';

  return (
    <div className={styles.row} data-testid={`template-field-${name}`}>
      <div className={styles.labelRow}>
        <label className={styles.label} htmlFor={id}>
          {label}
        </label>
        {defaultTemplate !== undefined && value !== defaultTemplate && (
          <button
            type="button"
            className={styles.resetDefault}
            data-testid={`reset-default-${name}`}
            onClick={() => onChange(defaultTemplate)}
          >
            Reset to default
          </button>
        )}
        <Popover
          label={`${label} token help`}
          trigger={<span aria-hidden>?</span>}
          triggerClassName={styles.helpTrigger}
        >
          <div className={styles.tokenHelp} data-testid={`token-help-${name}`}>
            <div className={styles.tokenHelpTitle}>Available tokens</div>
            <ul className={styles.tokenList}>
              {groups.map((g) => (
                <li key={g.field} className={styles.tokenItem}>
                  <code className={styles.tokenName}>{g.display}</code>
                  {g.aliases.length > 1 && (
                    <span className={styles.tokenAliases}>
                      {g.aliases.join(', ')}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </Popover>
      </div>
      <input
        id={id}
        type="text"
        className={styles.templateInput}
        value={value}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
      />
      <div className={styles.exampleLine} data-testid={`example-${name}`}>
        <span className={styles.exampleLabel}>Example:</span>{' '}
        <span className={styles.exampleValue}>
          {!renameEnabled ? (
            <em className={styles.exampleMuted}>
              renaming disabled — files keep their original names
            </em>
          ) : tokensError ? (
            <em className={styles.exampleMuted}>example unavailable</em>
          ) : tokensPending || tokens === undefined ? (
            <em className={styles.exampleMuted}>loading example…</em>
          ) : (
            example || <em className={styles.exampleMuted}>(empty)</em>
          )}
        </span>
      </div>
      {error && (
        <div className={styles.fieldError} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
