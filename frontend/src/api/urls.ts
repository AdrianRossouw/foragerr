/*
 * Shared API URL builders (FRG-UI-003/004).
 *
 * The library index and the series detail screen both point posters at the
 * LOCAL cover-cache endpoint — never an external ComicVine host. Keeping the
 * literal in one place stops the two call sites from drifting apart.
 */

/** Local cover-cache endpoint for a series poster. */
export function coverUrl(seriesId: number): string {
  return `/api/v1/series/${seriesId}/cover`;
}
