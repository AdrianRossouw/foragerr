import type { KeyboardEvent } from 'react';
import type { ChipTone, ProviderKindConfig, ProviderResource } from './providerTypes';
import styles from './settings.module.css';

/*
 * P11 settings card (FRG-UI-008/009): name, capability/status chips, and an
 * enable switch. The whole card is clickable (opens the edit modal); the
 * switch is a nested control that must not bubble into the card click.
 *
 * The switch is deliberately a BUTTON with role="switch" — the audit test
 * confines form-element JSX (input/select/textarea) to the schemaForm renderer.
 */

const CHIP_CLASS: Record<ChipTone, string> = {
  success: styles.chipSuccess,
  danger: styles.chipDanger,
  warning: styles.chipWarning,
  muted: styles.chipMuted,
};

export function ProviderCard({
  kind,
  provider,
  onEdit,
  onToggle,
}: {
  kind: ProviderKindConfig;
  provider: ProviderResource;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onEdit();
    }
  };

  return (
    <div
      className={styles.card}
      role="button"
      tabIndex={0}
      aria-label={`Edit ${provider.name}`}
      data-testid={`provider-card-${provider.id}`}
      onClick={onEdit}
      onKeyDown={onKeyDown}
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardName}>{provider.name}</span>
        <button
          type="button"
          role="switch"
          aria-checked={provider.enabled}
          aria-label={`Enable ${provider.name}`}
          className={
            provider.enabled
              ? `${styles.switch} ${styles.switchOn}`
              : styles.switch
          }
          onClick={(e) => {
            e.stopPropagation();
            onToggle(!provider.enabled);
          }}
        >
          <span className={styles.switchKnob} aria-hidden />
        </button>
      </div>
      <div className={styles.chipRow}>
        {kind.chips(provider).map((chip) => (
          <span key={chip.label} className={`${styles.chipBase} ${CHIP_CLASS[chip.tone]}`}>
            {chip.label}
          </span>
        ))}
      </div>
    </div>
  );
}
