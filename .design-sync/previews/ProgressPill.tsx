import { ProgressPill } from 'foragerr-frontend';

/** Complete, missing (monitored), and unmonitored-with-gaps states side by side. */
export const States = () => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
    <ProgressPill have={36} total={36} />
    <ProgressPill have={12} total={36} />
    <ProgressPill have={8} total={20} monitored={false} />
  </div>
);

/** A single issue outstanding vs. an empty series with nothing owned yet. */
export const EdgeCases = () => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
    <ProgressPill have={35} total={36} />
    <ProgressPill have={0} total={12} />
  </div>
);
