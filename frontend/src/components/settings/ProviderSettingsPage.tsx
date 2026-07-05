import { useState } from 'react';
import { Toolbar } from '../Toolbar';
import type { ImplementationSchema } from '../schemaForm/schemaTypes';
import { ProviderCard } from './ProviderCard';
import { ProviderModal } from './ProviderModal';
import { useProviders, useProviderSchemas, useSaveProvider } from './providerHooks';
import type { ProviderKindConfig, ProviderResource } from './providerTypes';
import styles from './settings.module.css';

/*
 * The generic provider settings screen (FRG-UI-008/009): Sonarr settings-page
 * skeleton — toolbar (Show Advanced, dirty-save affordance), underlined
 * section heading, P11 card grid of configured providers plus a `+` add card,
 * and the schema-driven add/edit modal.
 *
 * BOTH settings screens are this one component with a different kind config;
 * per-kind divergence is data (providerKinds.ts), never code.
 */

type ModalState =
  | { phase: 'pick' }
  | { phase: 'form'; schema: ImplementationSchema; provider?: ProviderResource };

export function ProviderSettingsPage({ kind }: { kind: ProviderKindConfig }) {
  const providers = useProviders(kind);
  const schemas = useProviderSchemas(kind);
  const save = useSaveProvider(kind);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [modal, setModal] = useState<ModalState | null>(null);

  const openAdd = () => {
    const available = schemas.data ?? [];
    if (available.length === 1) {
      setModal({ phase: 'form', schema: available[0] });
    } else if (available.length > 1) {
      setModal({ phase: 'pick' });
    }
  };

  const openEdit = (provider: ProviderResource) => {
    const schema = (schemas.data ?? []).find(
      (s) => s.implementation === provider.implementation,
    );
    if (schema) setModal({ phase: 'form', schema, provider });
  };

  const toggleEnabled = (provider: ProviderResource, enabled: boolean) => {
    save.mutate({ id: provider.id, body: { enabled } });
  };

  return (
    <>
      <Toolbar
        title={`Settings — ${kind.title}`}
        actions={
          <>
            <button
              type="button"
              className={styles.toolbarButton}
              aria-pressed={showAdvanced}
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
            </button>
            <button type="button" className={styles.toolbarButton} disabled>
              No Changes
            </button>
          </>
        }
      />
      <div className={styles.page}>
        <h2 className={styles.sectionHeading}>{kind.title}</h2>
        {providers.isLoading && <p className={styles.stateText}>Loading…</p>}
        {providers.isError && (
          <p className={styles.stateText}>Could not load {kind.title.toLowerCase()}.</p>
        )}
        {providers.data && (
          <div className={styles.cardGrid}>
            {providers.data.map((provider) => (
              <ProviderCard
                key={provider.id}
                kind={kind}
                provider={provider}
                onEdit={() => openEdit(provider)}
                onToggle={(enabled) => toggleEnabled(provider, enabled)}
              />
            ))}
            <button
              type="button"
              className={styles.addCard}
              aria-label={`Add ${kind.singular}`}
              onClick={openAdd}
            >
              +
            </button>
          </div>
        )}
      </div>
      {modal?.phase === 'pick' && (
        <div className={styles.overlay} onClick={() => setModal(null)}>
          <div
            className={styles.modal}
            role="dialog"
            aria-modal="true"
            aria-label={`Add ${kind.singular}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Add {kind.singular}</span>
              <button
                type="button"
                className={styles.iconButton}
                aria-label="Close"
                onClick={() => setModal(null)}
              >
                ×
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.pickerGrid}>
                {(schemas.data ?? []).map((schema) => (
                  <button
                    key={schema.implementation}
                    type="button"
                    className={styles.pickerCard}
                    onClick={() => setModal({ phase: 'form', schema })}
                  >
                    <span className={styles.cardName}>{schema.name}</span>
                    <span className={styles.pickerProtocol}>{schema.protocol}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      {modal?.phase === 'form' && (
        <ProviderModal
          kind={kind}
          schema={modal.schema}
          provider={modal.provider}
          showAdvanced={showAdvanced}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
}
