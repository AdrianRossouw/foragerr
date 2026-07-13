import { useState } from 'react';
import { MonitorToggle } from 'foragerr-frontend';

/** The bookmark toggle in both states: filled accent = monitored, hollow = not. */
export const BothStates = () => {
  const [monitored, setMonitored] = useState(true);
  const [unmonitored, setUnmonitored] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <MonitorToggle
          monitored={monitored}
          onToggle={() => setMonitored((m) => !m)}
          label="Saga"
        />
        <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>Monitored</span>
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <MonitorToggle
          monitored={unmonitored}
          onToggle={() => setUnmonitored((m) => !m)}
          label="Monstress"
        />
        <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>Unmonitored</span>
      </span>
    </div>
  );
};

/** Inline in a series-row context, next to a title. */
export const InSeriesRow = () => {
  const [monitored, setMonitored] = useState(true);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <MonitorToggle
        monitored={monitored}
        onToggle={() => setMonitored((m) => !m)}
        label="Saga"
      />
      <span style={{ fontWeight: 500 }}>Saga</span>
      <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>Image · 2012</span>
    </div>
  );
};

/** Larger size and the disabled (non-interactive) presentation. */
export const SizeAndDisabled = () => {
  const [monitored, setMonitored] = useState(true);
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
      <MonitorToggle
        monitored={monitored}
        onToggle={() => setMonitored((m) => !m)}
        label="issue 12"
        size={24}
      />
      <MonitorToggle monitored={false} onToggle={() => {}} label="issue 13" disabled />
      <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>size 24 · disabled</span>
    </div>
  );
};
