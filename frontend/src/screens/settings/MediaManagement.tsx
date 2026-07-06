import { useEffect, useMemo, useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { SchemaForm } from '../../components/schemaForm/SchemaForm';
import type {
  FieldValue,
  FieldValues,
  SchemaField,
} from '../../components/schemaForm/schemaTypes';
import { mapApiError } from '../../components/settings/apiErrors';
import {
  useCreateRootFolder,
  useDeleteRootFolder,
  useRootFolders,
  useSeriesIndex,
} from '../../api/hooks';
import type {
  MediaManagementConfig,
  NamingConfig,
  RootFolderResource,
} from '../../api/types';
import { formatBytes } from '../../lib/format';
import type { ExampleFields } from './naming/renderExample';
import { TemplateField } from './naming/TemplateField';
import { RenamePreviewPanel } from './naming/RenamePreviewPanel';
import {
  useMediaManagementConfig,
  useNamingConfig,
  useNamingTokens,
  usePutMediaManagementConfig,
  usePutNamingConfig,
} from './naming/namingHooks';
import styles from './naming/MediaManagement.module.css';

/*
 * Settings — Media Management & Naming (FRG-UI-012).
 *
 * A BESPOKE single-form settings page (Sonarr save-bar model) — not the
 * provider list+modal machinery, which is the wrong shape for typed config
 * singletons. Standard fields render through the SHARED `SchemaForm` renderer;
 * the two naming templates get bespoke `TemplateField`s (live example + `?`
 * token help). Save persists via the two typed config PUT endpoints
 * (FRG-API-013); a field-precise 4xx attaches to its field via the shared
 * `settings.`-prefix `mapApiError`. A per-series rename preview (FRG-PP-012)
 * launches from here.
 */

// Sample issue driving the live example line — display data (representative
// values keyed by canonical field), NOT a token list; the token names come from
// the backend vocabulary (GET /config/naming/tokens).
const EXAMPLE_FIELDS: ExampleFields = {
  series_title: 'Saga',
  series_cleantitle: 'Saga',
  volume: '1',
  year: '2012',
  issue: '5',
  issue_title: 'Chapter Five',
  classification: 'Regular',
  booktype: 'Print',
  release_group: 'DiG',
  issue_id: '12345',
  publisher: 'Image',
};

const NAMING_TOGGLE_FIELDS: SchemaField[] = [
  {
    order: 0,
    name: 'rename_enabled',
    type: 'checkbox',
    label: 'Rename Files',
    help: 'Rename imported files to match the templates below. When off, files keep their original names.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
];

const ILLEGAL_FIELD: SchemaField[] = [
  {
    order: 0,
    name: 'replace_illegal_characters',
    type: 'checkbox',
    label: 'Replace Illegal Characters',
    help: 'Replace characters that are illegal in file names with a space. When off, files with illegal characters are skipped.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
];

const IMPORT_FIELDS: SchemaField[] = [
  {
    order: 0,
    name: 'import_transfer_mode',
    type: 'textbox',
    label: 'Import Using',
    help: 'How completed downloads are placed into the library.',
    required: true,
    secret: false,
    advanced: false,
    selectOptions: [
      { value: 'move', name: 'Move' },
      { value: 'copy', name: 'Copy' },
      { value: 'hardlink', name: 'Hardlink' },
    ],
  },
  {
    order: 1,
    name: 'library_import_mode',
    type: 'textbox',
    label: 'Existing-Library Import',
    help: 'How files already under the library root are imported. In-place is the safe default.',
    required: true,
    secret: false,
    advanced: false,
    selectOptions: [
      { value: 'in_place', name: 'In place' },
      { value: 'move', name: 'Move' },
    ],
  },
  {
    order: 2,
    name: 'library_import_proposal_cap',
    type: 'number',
    label: 'Library Import Proposal Cap',
    help: 'Maximum number of ComicVine match proposals a single library-import scan fetches. Folder groups beyond the cap stage without a proposal — search them from the review screen.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 3,
    name: 'library_import_similarity_floor',
    type: 'number',
    label: 'Library Import Similarity Floor',
    help: 'Minimum name similarity (0 to 1) before a library-import scan proposes a ComicVine match on its own. Folder groups below the floor stage as no-match for manual search.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
];

const RECYCLE_FIELDS: SchemaField[] = [
  {
    order: 0,
    name: 'recycle_bin_path',
    type: 'textbox',
    label: 'Recycle Bin',
    help: 'Directory that superseded or deleted files are moved to. Leave blank to permanently delete.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 1,
    name: 'recycle_bin_retention_days',
    type: 'number',
    label: 'Recycle Bin Cleanup (days)',
    help: 'Permanently delete recycled files older than this many days. 0 keeps them forever.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
];

const DUPLICATE_FIELDS: SchemaField[] = [
  {
    order: 0,
    name: 'duplicate_constraint',
    type: 'textbox',
    label: 'Duplicate Constraint',
    help: 'How a duplicate at the same format-profile rung is resolved. Fixed releases ((f1)/(f2)) always win; profile upgrades are unaffected.',
    required: true,
    secret: false,
    advanced: false,
    selectOptions: [
      { value: 'larger-size', name: 'Larger size' },
      { value: 'preferred-format', name: 'Preferred format' },
    ],
  },
  {
    order: 1,
    name: 'duplicate_dump_path',
    type: 'textbox',
    label: 'Duplicate Dump Folder',
    help: 'Directory the losing duplicate is moved to (dated subfolders) instead of being deleted or recycled. Leave blank to use the normal replaced-file handling. Never pruned.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
];

const NAMING_NAMES = [
  'rename_enabled',
  'file_naming_template',
  'folder_naming_template',
  'replace_illegal_characters',
] as const;

const MM_NAMES = [
  'import_transfer_mode',
  'library_import_mode',
  'library_import_proposal_cap',
  'library_import_similarity_floor',
  'recycle_bin_path',
  'recycle_bin_retention_days',
  'duplicate_constraint',
  'duplicate_dump_path',
] as const;

const KNOWN_FIELDS: ReadonlySet<string> = new Set([...NAMING_NAMES, ...MM_NAMES]);

function baselineValues(
  naming: NamingConfig,
  mm: MediaManagementConfig,
): FieldValues {
  return { ...naming, ...mm };
}

/**
 * Coerce the raw form values into their PUT-payload form. This ONE function
 * feeds both the dirty check and the request bodies, so the two can never
 * disagree: without it a number field cleared to '' compares unequal to the
 * server's `0` forever (the save round-trips 0 back, but the '' in the form
 * state keeps the save bar armed), a dirty-loop the operator cannot clear.
 */
function normalize(values: FieldValues): NamingConfig & MediaManagementConfig {
  return {
    rename_enabled: values.rename_enabled === true,
    file_naming_template: String(values.file_naming_template ?? ''),
    folder_naming_template: String(values.folder_naming_template ?? ''),
    replace_illegal_characters: values.replace_illegal_characters === true,
    import_transfer_mode: String(values.import_transfer_mode ?? ''),
    library_import_mode: String(values.library_import_mode ?? ''),
    library_import_proposal_cap: Number(values.library_import_proposal_cap) || 0,
    library_import_similarity_floor:
      Number(values.library_import_similarity_floor) || 0,
    recycle_bin_path: String(values.recycle_bin_path ?? ''),
    recycle_bin_retention_days: Number(values.recycle_bin_retention_days) || 0,
    duplicate_constraint: String(values.duplicate_constraint ?? 'larger-size'),
    duplicate_dump_path: String(values.duplicate_dump_path ?? ''),
  };
}

interface SelectedSeries {
  id: number;
  title: string;
}

export function MediaManagement() {
  const namingQuery = useNamingConfig();
  const mmQuery = useMediaManagementConfig();
  const tokensQuery = useNamingTokens();
  const seriesQuery = useSeriesIndex();
  const putNaming = usePutNamingConfig();
  const putMm = usePutMediaManagementConfig();

  const [values, setValues] = useState<FieldValues | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [renameSeries, setRenameSeries] = useState<SelectedSeries | null>(null);

  // Seed the form once both config singletons have loaded (baseline == server).
  const naming = namingQuery.data;
  const mm = mmQuery.data;
  useEffect(() => {
    if (naming && mm && values === null) {
      setValues(baselineValues(naming, mm));
    }
  }, [naming, mm, values]);

  const baseline = useMemo(
    () => (naming && mm ? baselineValues(naming, mm) : null),
    [naming, mm],
  );

  // Diff in PUT-payload form (via `normalize`), never on the raw form values —
  // otherwise '' vs 0 on a cleared number field reads dirty forever after save.
  const normValues = values !== null ? normalize(values) : null;
  const normBaseline = baseline !== null ? normalize(baseline) : null;
  const namingDirty =
    normValues !== null &&
    normBaseline !== null &&
    NAMING_NAMES.some((n) => normValues[n] !== normBaseline[n]);
  const mmDirty =
    normValues !== null &&
    normBaseline !== null &&
    MM_NAMES.some((n) => normValues[n] !== normBaseline[n]);
  const dirty = namingDirty || mmDirty;
  const saving = putNaming.isPending || putMm.isPending;

  const onChange = (name: string, value: FieldValue) => {
    setFieldErrors({});
    setFormError(null);
    setValues((prev) => ({ ...(prev ?? {}), [name]: value }));
  };

  const onSave = async () => {
    if (values === null) return;
    setFieldErrors({});
    setFormError(null);
    const collectedFieldErrors: Record<string, string> = {};
    const collectedFormErrors: string[] = [];

    const collect = (error: unknown) => {
      const mapped = mapApiError(error, KNOWN_FIELDS);
      Object.assign(collectedFieldErrors, mapped.fieldErrors);
      if (mapped.formError) collectedFormErrors.push(mapped.formError);
    };

    const norm = normalize(values);
    if (namingDirty) {
      const body: NamingConfig = {
        rename_enabled: norm.rename_enabled,
        file_naming_template: norm.file_naming_template,
        folder_naming_template: norm.folder_naming_template,
        replace_illegal_characters: norm.replace_illegal_characters,
      };
      try {
        await putNaming.mutateAsync(body);
      } catch (error) {
        collect(error);
      }
    }
    if (mmDirty) {
      const body: MediaManagementConfig = {
        import_transfer_mode: norm.import_transfer_mode,
        library_import_mode: norm.library_import_mode,
        library_import_proposal_cap: norm.library_import_proposal_cap,
        library_import_similarity_floor: norm.library_import_similarity_floor,
        recycle_bin_path: norm.recycle_bin_path,
        recycle_bin_retention_days: norm.recycle_bin_retention_days,
        duplicate_constraint: norm.duplicate_constraint,
        duplicate_dump_path: norm.duplicate_dump_path,
      };
      try {
        await putMm.mutateAsync(body);
      } catch (error) {
        collect(error);
      }
    }
    setFieldErrors(collectedFieldErrors);
    setFormError(collectedFormErrors.join(' — ') || null);
  };

  const renameEnabled = values?.rename_enabled === true;
  const replaceIllegal = values?.replace_illegal_characters === true;

  return (
    <>
      <Toolbar
        title="Settings — Media Management"
        actions={
          <button
            type="button"
            className={styles.saveButton}
            disabled={!dirty || saving}
            onClick={onSave}
          >
            {saving ? 'Saving…' : dirty ? 'Save Changes' : 'No Changes'}
          </button>
        }
      />
      <div className={styles.page}>
        <RootFoldersSection />

        {(namingQuery.isLoading || mmQuery.isLoading || values === null) && (
          <p className={styles.stateText}>Loading settings…</p>
        )}
        {(namingQuery.isError || mmQuery.isError) && (
          <p className={styles.stateText}>Could not load media-management settings.</p>
        )}

        {values !== null && naming && mm && (
          <>
            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Naming</h2>
              <SchemaForm
                fields={NAMING_TOGGLE_FIELDS}
                values={values}
                onChange={onChange}
                errors={fieldErrors}
              />
              <TemplateField
                label="Standard File Format"
                name="file_naming_template"
                value={String(values.file_naming_template ?? '')}
                onChange={(v) => onChange('file_naming_template', v)}
                error={fieldErrors.file_naming_template}
                exampleFields={EXAMPLE_FIELDS}
                tokens={tokensQuery.data}
                tokensPending={tokensQuery.isPending}
                tokensError={tokensQuery.isError}
                isFile
                replaceIllegal={replaceIllegal}
                renameEnabled={renameEnabled}
              />
              <TemplateField
                label="Series Folder Format"
                name="folder_naming_template"
                value={String(values.folder_naming_template ?? '')}
                onChange={(v) => onChange('folder_naming_template', v)}
                error={fieldErrors.folder_naming_template}
                exampleFields={EXAMPLE_FIELDS}
                tokens={tokensQuery.data}
                tokensPending={tokensQuery.isPending}
                tokensError={tokensQuery.isError}
                isFile={false}
                replaceIllegal={replaceIllegal}
                renameEnabled={renameEnabled}
              />
              <SchemaForm
                fields={ILLEGAL_FIELD}
                values={values}
                onChange={onChange}
                errors={fieldErrors}
              />
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Importing</h2>
              <SchemaForm
                fields={IMPORT_FIELDS}
                values={values}
                onChange={onChange}
                errors={fieldErrors}
              />
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Recycle Bin</h2>
              <SchemaForm
                fields={RECYCLE_FIELDS}
                values={values}
                onChange={onChange}
                errors={fieldErrors}
              />
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Duplicate Handling</h2>
              <SchemaForm
                fields={DUPLICATE_FIELDS}
                values={values}
                onChange={onChange}
                errors={fieldErrors}
              />
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Rename Existing Files</h2>
              <p className={styles.sectionHelp}>
                Preview the renames the current templates would apply to a series
                already in your library. Nothing is changed until you confirm.
              </p>
              <SeriesRenamePicker onPick={setRenameSeries} series={seriesQuery.data} />
            </section>

            {formError && (
              <div className={styles.formError} role="alert">
                {formError}
              </div>
            )}
          </>
        )}
      </div>

      {renameSeries && (
        <RenamePreviewPanel
          seriesId={renameSeries.id}
          seriesTitle={renameSeries.title}
          onClose={() => setRenameSeries(null)}
        />
      )}
    </>
  );
}

/*
 * Root Folders (FRG-SER-008 / FRG-UI-012). Deliberately OUTSIDE the save-bar
 * form: registration and removal are immediate API actions (POST/DELETE
 * /api/v1/rootfolder), not config fields staged for a PUT — so the section
 * renders its own card-framed rows, never arms the save bar, and does not
 * depend on the config singletons having loaded. Validation failures render
 * the API's field-precise 400 message VERBATIM against the path input;
 * removal is a two-step inline confirm, and a 409 refusal (root still
 * referenced by series) surfaces its reason against the row.
 */
function RootFoldersSection() {
  const rootFolders = useRootFolders();
  const createRootFolder = useCreateRootFolder();
  const deleteRootFolder = useDeleteRootFolder();

  const [newPath, setNewPath] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [removeError, setRemoveError] = useState<{
    id: number;
    message: string;
  } | null>(null);

  const add = async () => {
    setAddError(null);
    try {
      await createRootFolder.mutateAsync({ path: newPath.trim() });
      setNewPath('');
    } catch (error) {
      // The fetcher's ApiRequestError carries the backend's uniform-shape
      // message verbatim (the field-precise 400 names the exact problem).
      setAddError(error instanceof Error ? error.message : String(error));
    }
  };

  const remove = async (id: number) => {
    setConfirmingId(null);
    setRemoveError(null);
    try {
      await deleteRootFolder.mutateAsync(id);
    } catch (error) {
      // A 409 refusal names the referencing-series count — shown verbatim.
      setRemoveError({
        id,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const rows = rootFolders.data ?? [];

  return (
    <section className={styles.section} data-testid="root-folders-section">
      <h2 className={styles.sectionHeading}>Root Folders</h2>
      <p className={styles.sectionHelp}>
        Library locations series are stored under. Adding and removing take
        effect immediately; removing never touches files on disk.
      </p>

      {rootFolders.isLoading && (
        <p className={styles.stateText}>Loading root folders…</p>
      )}
      {rootFolders.isError && (
        <p className={styles.fieldError} role="alert">
          Could not load root folders: {rootFolders.error.message}
        </p>
      )}
      {rootFolders.data && rows.length === 0 && (
        <p className={styles.stateText}>
          No root folders are registered yet. Add the folder your comics live
          in (an absolute path) below.
        </p>
      )}

      {rows.length > 0 && (
        <ul className={styles.rootFolderList}>
          {rows.map((folder: RootFolderResource) => (
            <li
              key={folder.id}
              className={styles.rootFolderRow}
              data-testid={`root-folder-${folder.id}`}
            >
              <span className={styles.rootFolderPath}>{folder.path}</span>
              <span className={styles.rootFolderFree}>
                {folder.free_space !== null
                  ? `${formatBytes(folder.free_space)} free`
                  : 'free space unknown'}
              </span>
              {confirmingId === folder.id ? (
                <>
                  <button
                    type="button"
                    className={`${styles.button} ${styles.buttonPrimary}`}
                    disabled={deleteRootFolder.isPending}
                    onClick={() => void remove(folder.id)}
                  >
                    Confirm Remove
                  </button>
                  <button
                    type="button"
                    className={styles.button}
                    onClick={() => setConfirmingId(null)}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className={styles.button}
                  aria-label={`Remove root folder ${folder.path}`}
                  onClick={() => {
                    setRemoveError(null);
                    setConfirmingId(folder.id);
                  }}
                >
                  Remove
                </button>
              )}
              {removeError?.id === folder.id && (
                <span className={styles.fieldError} role="alert">
                  {removeError.message}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className={styles.rootFolderAddRow}>
        <input
          className={styles.rootFolderInput}
          type="text"
          aria-label="New root folder path"
          placeholder="/path/to/comics"
          value={newPath}
          onChange={(e) => {
            setNewPath(e.target.value);
            setAddError(null);
          }}
        />
        <button
          type="button"
          className={`${styles.button} ${styles.buttonPrimary}`}
          disabled={newPath.trim() === '' || createRootFolder.isPending}
          onClick={() => void add()}
        >
          {createRootFolder.isPending ? 'Adding…' : 'Add Root Folder'}
        </button>
      </div>
      {addError && (
        <p className={styles.fieldError} role="alert" data-testid="root-folder-add-error">
          {addError}
        </p>
      )}
    </section>
  );
}

function SeriesRenamePicker({
  series,
  onPick,
}: {
  series: { id: number; title: string }[] | undefined;
  onPick: (s: SelectedSeries) => void;
}) {
  const [selectedId, setSelectedId] = useState<string>('');
  const rows = series ?? [];

  return (
    <div className={styles.renamePicker}>
      <select
        aria-label="Series to preview renames for"
        className={styles.picker}
        value={selectedId}
        onChange={(e) => setSelectedId(e.target.value)}
      >
        <option value="" disabled>
          Select a series…
        </option>
        {rows.map((s) => (
          <option key={s.id} value={String(s.id)}>
            {s.title}
          </option>
        ))}
      </select>
      <button
        type="button"
        className={styles.button}
        disabled={selectedId === ''}
        onClick={() => {
          const picked = rows.find((s) => String(s.id) === selectedId);
          if (picked) onPick({ id: picked.id, title: picked.title });
        }}
      >
        Preview Rename
      </button>
    </div>
  );
}
