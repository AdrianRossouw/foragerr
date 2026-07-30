import { useEffect, useState, type FormEvent } from 'react';
import { useComicVineConfig, usePutComicVineConfig } from './generalHooks';
import generalStyles from './General.module.css';
import styles from './NonComicPublishers.module.css';

/*
 * Settings -> General publisher-filtering panel (FRG-UI-046 / FRG-SRC-012):
 * the library-wide list that replaces the removed per-source Sources-screen
 * editor. Same GET/PUT /api/v1/config/general resource the ComicVine key and
 * ignore-list fields on this screen use; a dedicated mutation instance keeps
 * this save's pending state independent of theirs (all three PUT the same
 * endpoint but touch only the field they carry).
 *
 * Ships with curated, operator-removable defaults (not empty) — the value IS
 * the default set, shown and editable like any other entry, matching the CV
 * ignore list's posture rather than the old per-source panel's empty start.
 */

function parseEntries(value: string): string[] {
  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

function serializeEntries(entries: string[]): string {
  return entries.join(', ');
}

export function NonComicPublishers() {
  const configQuery = useComicVineConfig();
  const putConfig = usePutComicVineConfig();

  const resource = configQuery.data?.non_comic_publishers;
  const envManaged = resource?.source === 'env';
  // Serialized, not delimiter-joined: publisher names contain spaces and
  // commas separate entries, so the re-seed below stays a lossless
  // round-trip of the server's comma-separated string.
  const persistedKey = JSON.stringify(resource ? parseEntries(resource.value) : []);

  const [entries, setEntries] = useState<string[]>([]);
  const [draft, setDraft] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed from the server whenever the persisted value changes underneath
  // an UNEDITED editor (initial load, a save's own response). An edited
  // draft is never clobbered — the operator's in-progress list wins until
  // they save.
  useEffect(() => {
    if (dirty) return;
    setEntries(JSON.parse(persistedKey) as string[]);
  }, [persistedKey, dirty]);

  if (!configQuery.data) return null;

  const edit = (next: string[]) => {
    setEntries(next);
    setDirty(true);
    setSaved(false);
  };

  const addEntry = (e: FormEvent) => {
    e.preventDefault();
    const value = draft.trim();
    if (!value) return;
    // Case-insensitive de-dupe mirrors the server's own list cleaning, so
    // the editor never shows an entry the backend would silently drop.
    if (entries.some((entry) => entry.toLowerCase() === value.toLowerCase())) {
      setDraft('');
      return;
    }
    edit([...entries, value]);
    setDraft('');
  };

  const removeEntry = (value: string) => {
    edit(entries.filter((entry) => entry !== value));
  };

  const save = () => {
    if (putConfig.isPending) return;
    setError(null);
    putConfig.mutate(
      { non_comic_publishers: serializeEntries(entries) },
      {
        onSuccess: () => {
          setDirty(false);
          setSaved(true);
        },
        onError: (err) => setError(err.message),
      },
    );
  };

  return (
    <section className={generalStyles.section} data-testid="non-comic-publishers-panel">
      <h2 className={generalStyles.sectionHeading}>Non-Comic Publishers</h2>
      <p className={generalStyles.sectionHelp}>
        Some things in a bundle aren&apos;t comics — RPG rulebooks, tech-book
        PDFs, art books. List their publishers here and foragerr files them
        as Other, whatever the file type.
      </p>
      <p className={generalStyles.sectionHelp}>
        Changes take effect on the next sync. Items you&apos;ve already
        matched or ignored don&apos;t move.
      </p>

      {envManaged ? (
        <p
          className={generalStyles.envNote}
          role="status"
          data-testid="non-comic-publishers-env-managed"
        >
          Set by the <code>FORAGERR_NON_COMIC_PUBLISHERS</code> environment
          variable — managed outside the UI. To change it, edit the
          environment variable and restart foragerr.
        </p>
      ) : (
        <>
          {entries.length === 0 ? (
            <p className={styles.empty} data-testid="non-comic-publishers-empty">
              No publishers listed — every item is classified by its file
              shape alone.
            </p>
          ) : (
            <ul className={styles.list} data-testid="non-comic-publishers-list">
              {entries.map((entry) => (
                <li
                  key={entry}
                  className={styles.item}
                  data-testid={`non-comic-publisher-${entry}`}
                >
                  <span>{entry}</span>
                  <button
                    type="button"
                    className={styles.mutedBtn}
                    aria-label={`Remove ${entry}`}
                    onClick={() => removeEntry(entry)}
                    data-testid={`non-comic-publisher-remove-${entry}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          <form className={styles.form} onSubmit={addEntry}>
            <input
              className={styles.input}
              type="text"
              aria-label="Publisher to always file as Other"
              placeholder="Publisher name"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              data-testid="non-comic-publishers-input"
            />
            <button
              type="submit"
              className={styles.linkBtn}
              data-testid="non-comic-publishers-add"
            >
              Add
            </button>
          </form>

          <p className={generalStyles.sectionHelp}>
            An entry ending in <code>*</code> matches anything containing the
            name (for example <code>Paizo*</code>); any other entry must
            match exactly.
          </p>

          <div className={styles.actions}>
            <button
              type="button"
              className={generalStyles.saveButton}
              disabled={putConfig.isPending}
              onClick={save}
              data-testid="non-comic-publishers-save"
            >
              {putConfig.isPending ? 'Saving…' : 'Save non-comic publishers'}
            </button>
            {saved && !dirty && (
              <span className={styles.saved} role="status" data-testid="non-comic-publishers-saved">
                Saved — applies on the next sync.
              </span>
            )}
          </div>

          {error && (
            <p className={generalStyles.formError} role="alert" data-testid="non-comic-publishers-error">
              {error}
            </p>
          )}
        </>
      )}
    </section>
  );
}
