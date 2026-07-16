import type { ChipTone, ProviderKindConfig, ProviderResource } from './providerTypes';
import styles from './settings.module.css';

/*
 * P11 settings card (FRG-UI-008/009): name, capability/status chips, and an
 * enable switch. The card body stays mouse-clickable (opens the edit modal) for
 * convenience, but the keyboard/AT edit affordance is the provider NAME rendered
 * as a real <button> — the card wrapper carries NO interactive role/tabindex, so
 * the focusable enable switch is not nested inside another interactive control
 * (axe nested-interactive, FRG-UI-038). The name button keeps the "Edit <name>"
 * accessible name the e2e spine + SELECTORS.md rely on.
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
  return (
    <div
      className={styles.card}
      data-testid={`provider-card-${provider.id}`}
      onClick={onEdit}
    >
      <div className={styles.cardHeader}>
        <button
          type="button"
          className={styles.cardName}
          aria-label={`Edit ${provider.name}`}
          onClick={(e) => {
            // The card body also opens the edit modal on click; stop the bubble
            // so a name-button click doesn't fire onEdit twice.
            e.stopPropagation();
            onEdit();
          }}
        >
          {provider.name}
        </button>
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
