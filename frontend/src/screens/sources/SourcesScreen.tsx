import { Toolbar } from '../../components/Toolbar';
import { ConnectCard } from './ConnectCard';
import { StoreManage } from './StoreManage';
import { useSources } from '../../api/sourceHooks';
import type { SourceConnectionState } from '../../api/types';
import styles from './sources.module.css';

function statusDotClass(state: SourceConnectionState | 'none'): string {
  if (state === 'connected') return styles.dotConnected;
  if (state === 'expired') return styles.dotExpired;
  return styles.dotDisconnected;
}

/**
 * Sources hub (FRG-UI-029): the store rail — currently the one built store,
 * Humble Bundle — and its panel: the connect card when disconnected/expired,
 * or the manage view when connected. Session expiry and review live in the
 * sub-components. The rail is deliberately single-store; a second store tab
 * appears when a second integration actually ships.
 */
export function SourcesScreen() {
  const sources = useSources();

  const humble = (sources.data ?? []).find((s) => s.type === 'humble') ?? null;
  const humbleState: SourceConnectionState | 'none' =
    humble?.connection_state ?? 'none';
  const connected = humble?.connection_state === 'connected';

  return (
    <>
      <Toolbar title="Sources" />
      <div className={styles.content}>
        <div className={styles.rail} aria-label="Store sources">
          <span className={`${styles.tab} ${styles.tabActive}`}>
            <span
              className={`${styles.tabTile} ${styles.tileHumble}`}
              aria-hidden
            >
              <i className="fa-solid fa-bag-shopping" />
            </span>
            Humble Bundle
            <span
              className={`${styles.statusDot} ${statusDotClass(humbleState)}`}
              aria-hidden
            />
          </span>
        </div>

        {sources.isLoading && (
          <p className={styles.stateNote}>Loading sources…</p>
        )}

        {!sources.isLoading &&
          (connected && humble ? (
            <StoreManage source={humble} />
          ) : (
            <ConnectCard source={humble} />
          ))}
      </div>
    </>
  );
}
