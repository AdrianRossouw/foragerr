import { useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { ConnectCard } from './ConnectCard';
import { StoreManage } from './StoreManage';
import { useSources } from '../../api/sourceHooks';
import type { SourceConnectionState } from '../../api/types';
import styles from './sources.module.css';

type ActiveStore = 'humble' | '2000ad';

function statusDotClass(state: SourceConnectionState | 'none'): string {
  if (state === 'connected') return styles.dotConnected;
  if (state === 'expired') return styles.dotExpired;
  return styles.dotDisconnected;
}

function StoreTab({
  active,
  onClick,
  tileClass,
  icon,
  name,
  state,
}: {
  active: boolean;
  onClick: () => void;
  tileClass: string;
  icon: string;
  name: string;
  state: SourceConnectionState | 'none';
}) {
  return (
    <button
      type="button"
      className={`${styles.tab} ${active ? styles.tabActive : ''}`}
      onClick={onClick}
      aria-pressed={active}
    >
      <span className={`${styles.tabTile} ${tileClass}`} aria-hidden>
        <i className={`fa-solid ${icon}`} />
      </span>
      {name}
      <span
        className={`${styles.statusDot} ${statusDotClass(state)}`}
        aria-hidden
      />
    </button>
  );
}

/**
 * Sources hub (FRG-UI-029): the store rail (Humble built + a 2000 AD
 * not-yet-connected placeholder + "Add a source"), and the active store's panel
 * — the connect card when disconnected/expired, or the manage view when
 * connected. Session expiry and review live in the sub-components.
 */
export function SourcesScreen() {
  const sources = useSources();
  const [active, setActive] = useState<ActiveStore>('humble');

  const humble = (sources.data ?? []).find((s) => s.type === 'humble') ?? null;
  const humbleState: SourceConnectionState | 'none' =
    humble?.connection_state ?? 'none';
  const connected = humble?.connection_state === 'connected';

  return (
    <>
      <Toolbar title="Sources" />
      <div className={styles.content}>
        <div className={styles.rail} role="tablist" aria-label="Store sources">
          <StoreTab
            active={active === 'humble'}
            onClick={() => setActive('humble')}
            tileClass={styles.tileHumble}
            icon="fa-bag-shopping"
            name="Humble Bundle"
            state={humbleState}
          />
          <StoreTab
            active={active === '2000ad'}
            onClick={() => setActive('2000ad')}
            tileClass={styles.tile2000ad}
            icon="fa-bolt"
            name="2000 AD"
            state="none"
          />
          <button type="button" className={styles.addSource}>
            <i className="fa-solid fa-plus" aria-hidden /> Add a source
          </button>
        </div>

        {sources.isLoading && (
          <p className={styles.stateNote}>Loading sources…</p>
        )}

        {!sources.isLoading && active === 'humble' && (
          connected && humble ? (
            <StoreManage source={humble} />
          ) : (
            <ConnectCard source={humble} />
          )
        )}

        {active === '2000ad' && (
          <div className={styles.placeholder} data-testid="placeholder-2000ad">
            The 2000 AD store integration is not available yet. It is shown here
            as a placeholder for a future source.
          </div>
        )}
      </div>
    </>
  );
}
