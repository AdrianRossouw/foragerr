import { type CSSProperties, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { SegmentedControl } from '../../components/SegmentedControl';
import { InitialsAvatar } from '../../components/InitialsAvatar';
import { BookOpenIcon, CheckIcon, CloseIcon, PlusIcon } from '../../components/icons';
import { useCreatorsList, useSetCreatorFollow } from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type {
  CreatorResource,
  CreatorWorkRef,
  SeriesResource,
} from '../../api/types';
import { roleList } from '../../lib/roles';
import styles from './CreatorsScreen.module.css';

/**
 * Creators grid (FRG-UI-027), rendered to the design handoff §7: a responsive
 * card grid of library-credited creators, each card carrying a green-gradient
 * initials avatar, name, a `roles · N series` line, an explicit Follow/Following
 * pill (the ONLY follow entry point besides the profile), and a row of cover
 * spines for its library works. The header shows the `N creators · M followed`
 * aggregates and a followed-only filter; a `?seriesId=` focus (arrived at from a
 * series-detail credit) filters to that series' creators behind a dismissible
 * chip. All data is library-derived — no ComicVine call, no person images.
 */

type Scope = 'all' | 'following';

const SCOPE_OPTIONS = [
  { value: 'all' as const, label: 'All' },
  { value: 'following' as const, label: 'Following' },
];

/** The card spine's cover URL (local endpoint) when the work has a cached cover. */
function spineStyle(work: CreatorWorkRef): CSSProperties {
  if (!work.coverAvailable) return {};
  return {
    backgroundImage: `url(/api/v1/series/${work.seriesId}/cover)`,
  };
}

export function CreatorsScreen() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const queryClient = useQueryClient();

  // The backend rejects a non-positive seriesId (Query ge=1), so a `?seriesId=0`
  // that passes the digit regex would otherwise focus on an id the list read
  // 400s on. Treat 0 (and anything below 1) as no focus at all.
  const rawSeriesId = searchParams.get('seriesId');
  const parsedSeriesId =
    rawSeriesId !== null && /^\d+$/.test(rawSeriesId) ? Number(rawSeriesId) : null;
  const focusId = parsedSeriesId !== null && parsedSeriesId >= 1 ? parsedSeriesId : null;

  // The followed-only filter is a URL param too, so it survives back/refresh and
  // a profile round-trip (the profile's back link returns to this exact URL).
  const followedOnly = searchParams.get('followed') === 'true';
  const scope: Scope = followedOnly ? 'following' : 'all';

  const list = useCreatorsList({
    followed: followedOnly || undefined,
    seriesId: focusId ?? undefined,
  });
  const result = list.data;
  const records = useMemo(() => result?.records ?? [], [result]);

  const follow = useSetCreatorFollow();

  const setScope = (next: Scope) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === 'following') params.set('followed', 'true');
        else params.delete('followed');
        return params;
      },
      { replace: true },
    );
  };

  const clearFocus = () => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.delete('seriesId');
        return params;
      },
      { replace: true },
    );
  };

  // The focus chip names the series without a second request. Prefer the
  // client-side library index (the same ['series'] cache HeaderQuickSearch
  // reads via useSeriesIndex): a card's work refs are capped (WORKS_CAP), so for
  // a prolific creator the focused series can be absent from every visible row.
  // Fall back to a work-ref scan, then the generic label.
  const focusTitle = useMemo(() => {
    if (focusId === null) return null;
    const index = queryClient.getQueryData<SeriesResource[]>(
      queryKeys.series.all(),
    );
    const fromIndex = index?.find((s) => s.id === focusId);
    if (fromIndex) return fromIndex.title;
    for (const creator of records) {
      const work = creator.works.find((w) => w.seriesId === focusId);
      if (work) return work.title;
    }
    return null;
  }, [focusId, records, queryClient]);

  const countLine = result
    ? `${result.totalCreators} creator${result.totalCreators === 1 ? '' : 's'} · ` +
      `${result.followedCreators} followed`
    : '';

  const renderCard = (creator: CreatorResource) => {
    const followed = creator.followed;
    const seriesText = `${creator.seriesCount} series`;
    return (
      <div
        key={creator.id}
        className={styles.card}
        data-testid={`creator-card-${creator.id}`}
      >
        <div className={styles.cardTop}>
          <button
            type="button"
            className={styles.identity}
            onClick={() => navigate(`/creators/${creator.id}`)}
          >
            <InitialsAvatar name={creator.name} size={46} />
            <span className={styles.identityText}>
              <span className={styles.name}>{creator.name}</span>
              <span className={styles.roleLine}>
                {roleList(creator.roles)}
                {creator.roles.length > 0 ? ' · ' : ''}
                {seriesText}
              </span>
            </span>
          </button>
          <button
            type="button"
            className={followed ? `${styles.pill} ${styles.pillOn}` : styles.pill}
            aria-pressed={followed}
            aria-label={`${followed ? 'Unfollow' : 'Follow'} ${creator.name}`}
            disabled={follow.isPending && follow.variables?.creatorId === creator.id}
            onClick={() =>
              follow.mutate({ creatorId: creator.id, followed: !followed })
            }
          >
            {followed ? <CheckIcon size={12} /> : <PlusIcon size={12} />}
            {followed ? 'Following' : 'Follow'}
          </button>
        </div>
        {creator.works.length > 0 && (
          <div className={styles.spines}>
            {creator.works.map((work) => (
              <button
                type="button"
                key={work.seriesId}
                className={styles.spine}
                style={spineStyle(work)}
                title={work.title}
                aria-label={`Open ${work.title}`}
                onClick={() => navigate(`/series/${work.seriesId}`)}
              />
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <Toolbar
        title="Creators"
        actions={
          <SegmentedControl
            options={SCOPE_OPTIONS}
            value={scope}
            onChange={setScope}
            ariaLabel="Follow filter"
          />
        }
      />
      <div className={styles.screen}>
        <div className={styles.headerRow}>
          <span className={styles.countLine}>{countLine}</span>
          {focusId !== null && (
            <button
              type="button"
              className={styles.focusChip}
              onClick={clearFocus}
              aria-label="Clear series focus"
            >
              {focusTitle ?? 'This series'}
              <CloseIcon size={11} />
            </button>
          )}
        </div>

        {list.isLoading && (
          <p className={styles.stateMsg}>Loading creators…</p>
        )}
        {list.isError && (
          <p className={styles.stateMsg}>Could not load creators.</p>
        )}

        {!list.isLoading && !list.isError && records.length === 0 && (
          <div className={styles.empty} data-testid="creators-empty">
            <div className={styles.emptyIcon} aria-hidden>
              <BookOpenIcon size={30} />
            </div>
            {followedOnly ? (
              <div>You&rsquo;re not following any creators yet.</div>
            ) : (
              <div>
                No creator credits yet.
                <div className={styles.emptySub}>
                  Credits arrive with metadata refreshes — new series bring them
                  automatically; run creators-backfill under System &rsaquo; Tasks
                  to gather them for existing series.
                </div>
              </div>
            )}
          </div>
        )}

        {records.length > 0 && (
          <div className={styles.grid} data-testid="creators-grid">
            {records.map(renderCard)}
          </div>
        )}
      </div>
    </>
  );
}
