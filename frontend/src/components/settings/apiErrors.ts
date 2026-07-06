import { ApiRequestError } from '../../api/fetcher';

/*
 * Uniform-error -> field mapping for settings screens (FRG-UI-008/009/012).
 *
 * The backend names each offending setting under a `settings.` prefix in the
 * uniform 4xx body (`{message, errors:[{field, message}]}`). This strips that
 * prefix and routes each error onto the specific field it concerns, so a
 * field-precise validation failure attaches to its input rather than a bare
 * form-level banner. Errors that match no known field (or a mix) fall back to a
 * form-level message. Shared verbatim by the provider modal and the naming /
 * media-management settings page so both use ONE mapping.
 */
export function mapApiError(
  error: unknown,
  knownFields: ReadonlySet<string>,
): { fieldErrors: Record<string, string>; formError: string | null } {
  if (!(error instanceof ApiRequestError) || !error.body) {
    return {
      fieldErrors: {},
      formError: error instanceof Error ? error.message : 'Request failed',
    };
  }
  const fieldErrors: Record<string, string> = {};
  const unmatched: string[] = [];
  for (const entry of error.body.errors) {
    const name = entry.field?.replace(/^settings\./, '');
    if (name && knownFields.has(name)) {
      fieldErrors[name] = entry.message;
    } else {
      unmatched.push(entry.message);
    }
  }
  const formError =
    Object.keys(fieldErrors).length === 0 || unmatched.length > 0
      ? [error.body.message, ...unmatched].filter(Boolean).join(' — ')
      : null;
  return { fieldErrors, formError };
}
