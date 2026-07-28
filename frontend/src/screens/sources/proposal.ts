import type {
  EntitlementProposal,
  EntitlementProposedMatch,
  EntitlementResource,
} from '../../api/types';

/*
 * What the automatic proposal pass concluded about ONE row (FRG-SRC-010 /
 * FRG-UI-039), reduced to the three states the UI actually renders.
 *
 * The wire carries three shapes and the difference matters to the operator:
 *
 *   - a candidate       -> a library match or a ComicVine add is offered
 *   - a verdict marker  -> the pass RAN and found nothing plausible
 *   - null              -> the pass has NOT run for this row yet (deferred,
 *                          e.g. the CV budget ceiling) — it is retryable
 *
 * Only the first is actionable as a proposal; the other two are informational
 * text beside the ever-present row search, never a dead end. This is
 * deliberately defensive about the marker's exact spelling: a marker with no
 * `kind`, an explicit `verdict`, or an empty candidate set with no id all read
 * as "looked, found nothing" rather than being mistaken for a candidate.
 */

export type ProposalState =
  | { kind: 'candidate'; candidate: EntitlementProposedMatch }
  | { kind: 'no-plausible-match' }
  | { kind: 'not-computed' };

function isCandidate(
  proposal: EntitlementProposal,
): proposal is EntitlementProposedMatch {
  const asVerdict = proposal as { verdict?: unknown; candidates?: unknown };
  if (typeof asVerdict.verdict === 'string') return false;
  const asCandidate = proposal as Partial<EntitlementProposedMatch>;
  if (asCandidate.kind !== 'library' && asCandidate.kind !== 'comicvine') {
    return false;
  }
  // A "candidate" that names nothing to act on is not one.
  return (
    asCandidate.series_id != null ||
    asCandidate.cv_volume_id != null ||
    asCandidate.title != null
  );
}

export function proposalState(entitlement: EntitlementResource): ProposalState {
  const proposal = entitlement.proposed_match;
  if (proposal == null) return { kind: 'not-computed' };
  if (isCandidate(proposal)) return { kind: 'candidate', candidate: proposal };
  return { kind: 'no-plausible-match' };
}

/** The proposed candidate, or null for either non-actionable state. */
export function proposedCandidate(
  entitlement: EntitlementResource,
): EntitlementProposedMatch | null {
  const state = proposalState(entitlement);
  return state.kind === 'candidate' ? state.candidate : null;
}
