import { useEffect, useState, type FormEvent } from 'react';
import { useUpdateSource } from '../../api/sourceHooks';
import type { StoreSourceResource } from '../../api/types';
import styles from './sources.module.css';

/**
 * A STARTER list, offered and never applied (owner rule 2026-07-11: no
 * intent-presuming defaults). These are the RPG/sourcebook publishers whose
 * PDF-shaped items dominated the dogfood corpus's false "comic" classifications
 * — pressing the button FILLS THE EDITOR so the operator can prune it and then
 * deliberately Save. Nothing here is written until they do.
 */
const STARTER_PUBLISHERS = [
  'Chaosium',
  'Paizo',
  'Pelgrane Press',
  'Free League',
  'Modiphius',
  'Cubicle 7',
  'Wizards of the Coast',
  'Kobold Press',
  'Monte Cook Games',
  'Goodman Games',
  'Evil Hat',
  'Green Ronin',
];

/** The source's currently-persisted rules out of its PUBLIC settings view. */
function storedRules(source: StoreSourceResource): string[] {
  const value = source.settings.publisher_rules;
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

/**
 * Publisher rules editor (FRG-SRC-012): the per-source list of publishers whose
 * items are always classified as Other, whatever their file shape — the
 * RPG-sourcebook escape hatch for a review queue full of PDFs that are not
 * comics.
 *
 * Ships EMPTY. Add/remove edit a local draft; Save PATCHes the WHOLE list (the
 * server contract is a whole-list replace, so `[]` clears the rules). The
 * change takes effect on the next sync and only over rows the automatic
 * classifier still owns — anything already matched or ignored never moves
 * (FRG-SRC-004's sticky decisions), which is what the panel says out loud.
 */
export function PublisherRules({ source }: { source: StoreSourceResource }) {
  const persisted = storedRules(source);
  // Serialized, not delimiter-joined: publisher names contain spaces, so the
  // re-seed below stays a lossless round-trip ("Pelgrane Press" is ONE rule).
  const persistedKey = JSON.stringify(persisted);

  const [open, setOpen] = useState(false);
  const [rules, setRules] = useState<string[]>(persisted);
  const [draft, setDraft] = useState('');
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const update = useUpdateSource();

  // Re-seed from the server whenever the persisted list changes underneath an
  // UNEDITED editor (a save's refetch, another tab). An edited draft is never
  // clobbered — the operator's in-progress list wins until they save or close.
  useEffect(() => {
    if (dirty) return;
    setRules(JSON.parse(persistedKey) as string[]);
  }, [persistedKey, dirty]);

  const edit = (next: string[]) => {
    setRules(next);
    setDirty(true);
    setSaved(false);
  };

  const addRule = (e: FormEvent) => {
    e.preventDefault();
    const value = draft.trim();
    if (!value) return;
    // Case-insensitive de-dupe mirrors the server's own list cleaning, so the
    // editor never shows a rule the backend would silently drop.
    if (rules.some((r) => r.toLowerCase() === value.toLowerCase())) {
      setDraft('');
      return;
    }
    edit([...rules, value]);
    setDraft('');
  };

  const save = () => {
    if (update.isPending) return;
    setError(null);
    update.mutate(
      { sourceId: source.id, publisher_rules: rules },
      {
        onSuccess: () => {
          setDirty(false);
          setSaved(true);
        },
        // The 409 case is "this source has no settings envelope to write into"
        // (it was disconnected): the honest fix is reconnect, so say so.
        onError: (err) => setError(err.message),
      },
    );
  };

  return (
    <div className={styles.rulesPanel} data-testid="publisher-rules">
      <button
        type="button"
        className={styles.rulesToggle}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        data-testid="publisher-rules-toggle"
      >
        <i
          className={`fa-solid ${open ? 'fa-chevron-up' : 'fa-chevron-down'}`}
          aria-hidden
        />{' '}
        Publisher rules
        <span className={styles.rulesCount}>
          {persisted.length === 0 ? 'none' : `${persisted.length} publisher${persisted.length === 1 ? '' : 's'}`}
        </span>
      </button>

      {open && (
        <div className={styles.rulesBody}>
          <p className={styles.rulesHelp}>
            Items from these publishers are always filed as Other, whatever
            their file format — the RPG-sourcebook escape hatch. Rules apply on
            the next sync and only to items you have not reviewed yet; anything
            already matched or ignored stays where you put it.
          </p>

          {rules.length === 0 ? (
            <p className={styles.rulesEmpty} data-testid="rules-empty">
              No publisher rules — every item is classified by its file shape
              alone.
            </p>
          ) : (
            <ul className={styles.rulesList} data-testid="rules-list">
              {rules.map((rule) => (
                <li key={rule} className={styles.ruleItem} data-testid={`rule-${rule}`}>
                  <span>{rule}</span>
                  <button
                    type="button"
                    className={styles.mutedBtn}
                    aria-label={`Remove ${rule}`}
                    onClick={() => edit(rules.filter((r) => r !== rule))}
                    data-testid={`rule-remove-${rule}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          <form className={styles.rulesForm} onSubmit={addRule}>
            <input
              className={styles.rowSearchInput}
              type="text"
              aria-label="Publisher to always file as Other"
              placeholder="Publisher name"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              data-testid="rule-input"
            />
            <button type="submit" className={styles.linkBtn} data-testid="rule-add">
              Add
            </button>
          </form>

          <div className={styles.rulesActions}>
            <button
              type="button"
              className={styles.mutedBtn}
              onClick={() => edit(STARTER_PUBLISHERS)}
              title="Fills the editor — nothing is saved until you press Save"
              data-testid="rules-starter"
            >
              Suggested starter list
            </button>
            <button
              type="button"
              className={styles.linkBtn}
              disabled={update.isPending}
              onClick={save}
              data-testid="rules-save"
            >
              {update.isPending ? 'Saving…' : 'Save rules'}
            </button>
            {saved && !dirty && (
              <span className={styles.rulesSaved} role="status" data-testid="rules-saved">
                Saved — applies on the next sync.
              </span>
            )}
          </div>

          {error && (
            <p className={styles.connectError} role="alert" data-testid="rules-error">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
