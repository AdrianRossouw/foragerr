import { useNavigate, useParams } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { InitialsAvatar } from '../../components/InitialsAvatar';
import { Poster } from '../../components/Poster';
import { ProgressStrip } from '../../components/ProgressStrip';
import { CheckIcon, PlusIcon } from '../../components/icons';
import {
  useCreatorBibliography,
  useCreatorProfile,
  useSetCreatorFollow,
} from '../../api/hooks';
import type {
  AddSeriesNavigationState,
  BibliographyEntry,
  CreatorSeriesStat,
} from '../../api/types';
import { publisherTint, roleChip } from '../../theme/palettes';
import { roleLabel, roleList } from '../../lib/roles';
import styles from './CreatorProfile.module.css';

/**
 * Creator profile (FRG-UI-028), rendered to the design handoff §8: a gradient
 * header carrying the large initials avatar, name, roles + publishers lines, and
 * a Follow/Following button; three stat columns (Series · owned-of-total issues
 * in library · Publishers); an "In your library" section of work cards —
 * local cover, title, this creator's role chips, a meta line, and the
 * whole-series owned/total progress bar (house progress styling) — each opening
 * the series detail; and a "More from <name>" section (FRG-API-024) of the
 * creator's cached external bibliography as add hand-off cards — a tinted title
 * placeholder, title, publisher/year meta line, and an "Add to library" button
 * routing into the standard add flow prefilled for that volume (the system never
 * adds a series from this section by itself). While the first bibliography fetch
 * is pending the section shows an unobtrusive gathering line; a fresh-but-empty
 * (or entirely-in-library) bibliography renders no section at all. An unknown
 * creator id renders the standard not-found state.
 */

function WorkCard({
  work,
  onOpen,
}: {
  work: CreatorSeriesStat;
  onOpen: () => void;
}) {
  const metaParts = [work.publisher ?? 'Unknown publisher'];
  metaParts.push(`${work.totalIssues} issue${work.totalIssues === 1 ? '' : 's'}`);
  return (
    <button
      type="button"
      className={styles.workCard}
      data-testid={`work-card-${work.seriesId}`}
      onClick={onOpen}
    >
      <Poster
        initial={work.title.charAt(0)}
        src={`/api/v1/series/${work.seriesId}/cover`}
        alt={`${work.title} cover`}
        frameClassName={styles.workCover}
        fallbackClassName={styles.workFallback}
        lazy
      />
      <span className={styles.workBody}>
        <span className={styles.workTitle}>{work.title}</span>
        <span className={styles.roleChips}>
          {work.roles.map((role) => {
            const c = roleChip(role);
            return (
              <span
                key={role}
                className={styles.roleChip}
                style={{ background: c.bg, color: c.text }}
              >
                {roleLabel(role)}
              </span>
            );
          })}
        </span>
        <span className={styles.workMeta}>{metaParts.join(' · ')}</span>
        <span className={styles.workSpacer} />
        <span className={styles.progressWrap}>
          <ProgressStrip
            have={work.ownedIssues}
            total={work.totalIssues}
            variant="strip"
          />
        </span>
      </span>
      <span className={styles.srOnly}>{`Open ${work.title} — credited as ${roleList(
        work.roles,
      )}`}</span>
    </button>
  );
}

/**
 * One "More from" card (FRG-UI-028): a tinted title placeholder (the handoff's
 * no-image card — the bibliography carries no local cover), the volume title, a
 * publisher · year · issue-count meta line, and an "Add to library" button. The
 * bibliography rows carry NO role, so no role chip is rendered (rather than a
 * faked one). The Add button hands off to the standard add flow prefilled with
 * the volume title — the ONLY way this section can lead to a series being added,
 * and only once the user completes that flow.
 */
function MoreFromCard({
  entry,
  onAdd,
}: {
  entry: BibliographyEntry;
  onAdd: () => void;
}) {
  const metaParts: string[] = [entry.publisher ?? 'Unknown publisher'];
  if (entry.startYear != null) metaParts.push(String(entry.startYear));
  if (entry.countOfIssues != null) {
    metaParts.push(`${entry.countOfIssues} issue${entry.countOfIssues === 1 ? '' : 's'}`);
  }
  return (
    <div className={styles.moreCard} data-testid={`more-card-${entry.cvVolumeId}`}>
      <span
        className={styles.morePlaceholder}
        style={{ background: publisherTint(entry.publisher) }}
        aria-hidden
      >
        {entry.title}
      </span>
      <span className={styles.moreBody}>
        <span className={styles.moreTitle}>{entry.title}</span>
        <span className={styles.moreMeta}>{metaParts.join(' · ')}</span>
        <span className={styles.moreSpacer} />
        <button
          type="button"
          className={styles.addBtn}
          aria-label={`Add ${entry.title} to library`}
          onClick={onAdd}
        >
          <PlusIcon size={11} />
          Add to library
        </button>
      </span>
    </div>
  );
}

export function CreatorProfile() {
  const { id } = useParams();
  const creatorId = Number(id);
  const navigate = useNavigate();

  const profileQuery = useCreatorProfile(creatorId);
  const bibliographyQuery = useCreatorBibliography(creatorId);
  const follow = useSetCreatorFollow();

  if (profileQuery.isLoading) {
    return (
      <>
        <Toolbar title="Creator" />
        <p className={styles.stateMsg}>Loading creator…</p>
      </>
    );
  }

  if (profileQuery.isError || !profileQuery.data) {
    return (
      <>
        <Toolbar title="Creator" />
        <div className={styles.notFound} data-testid="creator-not-found">
          <h1 className={styles.notFoundTitle}>Creator not found</h1>
          <p className={styles.notFoundBody}>
            This creator isn&rsquo;t in your library&rsquo;s credits.
          </p>
          <button
            type="button"
            className={styles.backButton}
            onClick={() => navigate('/creators')}
          >
            Back to creators
          </button>
        </div>
      </>
    );
  }

  const creator = profileQuery.data;
  const stats = creator.stats;
  const followed = creator.followed;

  const publishers = Array.from(
    new Set(
      creator.series
        .map((s) => s.publisher)
        .filter((p): p is string => p !== null && p !== ''),
    ),
  );

  // "More from" bibliography (FRG-API-024): the endpoint always serves whatever
  // cache rows survive its in-library anti-join plus a self-reported `state`.
  // Render the cards whenever there ARE rows (even while `pending` — stale-while-
  // revalidate); show the unobtrusive gathering line only when a fetch is
  // `pending` with zero rows; render NOTHING for a fresh-but-empty bibliography
  // (or while the first read is still loading) — no empty section shell.
  const bibliography = bibliographyQuery.data;
  const moreEntries = bibliography?.records ?? [];
  const bibliographyPending = bibliography?.state === 'pending';
  const goAdd = (term: string): void => {
    const state: AddSeriesNavigationState = { prefillTerm: term };
    navigate('/add', { state });
  };

  return (
    <>
      <Toolbar title={creator.name} />
      <div className={styles.content}>
        <header className={styles.hero}>
          <div className={styles.heroTop}>
            <InitialsAvatar name={creator.name} size={82} className={styles.heroAvatar} />
            <div className={styles.heroText}>
              <h1 className={styles.name}>{creator.name}</h1>
              <div className={styles.roles}>{roleList(creator.roles)}</div>
              {publishers.length > 0 && (
                <div className={styles.publishers}>{publishers.join(' · ')}</div>
              )}
            </div>
            <button
              type="button"
              className={
                followed ? `${styles.followBtn} ${styles.followBtnOn}` : styles.followBtn
              }
              aria-pressed={followed}
              aria-label={`${followed ? 'Unfollow' : 'Follow'} ${creator.name}`}
              disabled={follow.isPending}
              onClick={() =>
                follow.mutate({ creatorId: creator.id, followed: !followed })
              }
            >
              {followed ? <CheckIcon size={13} /> : <PlusIcon size={13} />}
              {followed ? 'Following' : 'Follow'}
            </button>
          </div>
          <div className={styles.statRow}>
            <div className={styles.stat}>
              <div className={styles.statValue} data-testid="stat-series">
                {stats.seriesCount}
              </div>
              <div className={styles.statLabel}>Series</div>
            </div>
            <div className={styles.statDivider} aria-hidden />
            <div className={styles.stat}>
              <div className={styles.statValue} data-testid="stat-issues">
                {stats.ownedIssues}{' '}
                <span className={styles.statSub}>/ {stats.totalIssues}</span>
              </div>
              <div className={styles.statLabel}>Issues in library</div>
            </div>
            <div className={styles.statDivider} aria-hidden />
            <div className={styles.stat}>
              <div className={styles.statValue} data-testid="stat-publishers">
                {stats.publisherCount}
              </div>
              <div className={styles.statLabel}>Publishers</div>
            </div>
          </div>
        </header>

        <div className={styles.body}>
          <button
            type="button"
            className={styles.backButton}
            onClick={() => navigate('/creators')}
          >
            <i className="fa-solid fa-chevron-left" aria-hidden /> Creators
          </button>

          {creator.series.length > 0 && (
            <section className={styles.section}>
              <div className={styles.sectionHead}>
                <span className={styles.sectionLabel}>In your library</span>
                <span className={styles.sectionCount}>{stats.seriesCount}</span>
              </div>
              <div className={styles.workGrid} data-testid="creator-works">
                {creator.series.map((work) => (
                  <WorkCard
                    key={work.seriesId}
                    work={work}
                    onOpen={() => navigate(`/series/${work.seriesId}`)}
                  />
                ))}
              </div>
            </section>
          )}

          {moreEntries.length > 0 ? (
            <section className={styles.section} data-testid="creator-more-from">
              <div className={styles.sectionHead}>
                <span className={styles.sectionLabel}>More from {creator.name}</span>
                <span className={styles.sectionCount}>{moreEntries.length}</span>
              </div>
              <p className={styles.moreSubline}>
                Not in your library yet — subscribe to any of these to start
                tracking them.
              </p>
              <div className={styles.moreGrid}>
                {moreEntries.map((entry) => (
                  <MoreFromCard
                    key={entry.cvVolumeId}
                    entry={entry}
                    onAdd={() => goAdd(entry.title)}
                  />
                ))}
              </div>
            </section>
          ) : bibliographyPending ? (
            <p className={styles.gathering} data-testid="creator-more-gathering">
              Gathering {creator.name}&rsquo;s bibliography from ComicVine…
            </p>
          ) : null}
        </div>
      </div>
    </>
  );
}

/**
 * Route wrapper (FRG-UI-028): key the profile by the URL id so all view-local
 * state resets when navigating creator→creator, mirroring SeriesDetailRoute.
 */
export function CreatorProfileRoute() {
  const { id } = useParams();
  return <CreatorProfile key={id} />;
}
