import { useEffect, useMemo, useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { SchemaForm } from '../../components/schemaForm/SchemaForm';
import type {
  FieldValue,
  FieldValues,
  SchemaField,
} from '../../components/schemaForm/schemaTypes';
import { mapApiError } from '../../components/settings/apiErrors';
import { useSeriesIndex } from '../../api/hooks';
import type {
  MediaManagementConfig,
  NamingConfig,
} from '../../api/types';
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

const NAMING_NAMES = [
  'rename_enabled',
  'file_naming_template',
  'folder_naming_template',
  'replace_illegal_characters',
] as const;

const MM_NAMES = [
  'import_transfer_mode',
  'library_import_mode',
  'recycle_bin_path',
  'recycle_bin_retention_days',
] as const;

const KNOWN_FIELDS: ReadonlySet<string> = new Set([...NAMING_NAMES, ...MM_NAMES]);

function baselineValues(
  naming: NamingConfig,
  mm: MediaManagementConfig,
): FieldValues {
  return { ...naming, ...mm };
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

  const namingDirty =
    values !== null &&
    baseline !== null &&
    NAMING_NAMES.some((n) => values[n] !== baseline[n]);
  const mmDirty =
    values !== null &&
    baseline !== null &&
    MM_NAMES.some((n) => values[n] !== baseline[n]);
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

    if (namingDirty) {
      const body: NamingConfig = {
        rename_enabled: values.rename_enabled === true,
        file_naming_template: String(values.file_naming_template ?? ''),
        folder_naming_template: String(values.folder_naming_template ?? ''),
        replace_illegal_characters: values.replace_illegal_characters === true,
      };
      try {
        await putNaming.mutateAsync(body);
      } catch (error) {
        collect(error);
      }
    }
    if (mmDirty) {
      const body: MediaManagementConfig = {
        import_transfer_mode: String(values.import_transfer_mode ?? ''),
        library_import_mode: String(values.library_import_mode ?? ''),
        recycle_bin_path: String(values.recycle_bin_path ?? ''),
        recycle_bin_retention_days: Number(values.recycle_bin_retention_days) || 0,
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
