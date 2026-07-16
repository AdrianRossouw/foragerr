import { Link, useLocation } from 'react-router-dom';
import { Toolbar } from '../components/Toolbar';
import styles from './NotFound.module.css';

/**
 * Catch-all not-found screen (FRG-UI-036). Rendered inside the app shell for any
 * route the SPA does not define, so an unknown path (e.g. a stale
 * `/settings/media` bookmark) shows the shell + an explanation and a link home
 * rather than a blank page.
 */
export function NotFound() {
  const location = useLocation();
  return (
    <>
      <Toolbar title="Page not found" />
      <div className={styles.screen} data-testid="not-found">
        <div className={styles.code} aria-hidden>
          404
        </div>
        <p className={styles.message}>
          There is nothing at <code>{location.pathname}</code>. The page may have
          moved or the link may be out of date.
        </p>
        <Link to="/" className={styles.homeLink}>
          Back to the library
        </Link>
      </div>
    </>
  );
}
