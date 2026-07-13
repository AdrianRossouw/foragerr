import { useState } from 'react';
import { Toggle } from 'foragerr-frontend';

/** Controlled on/off pair — the account bar's "Auto-sync new purchases" idiom. */
export const OnOff = () => {
  const [on, setOn] = useState(true);
  const [off, setOff] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
      <Toggle checked={on} onChange={setOn} label="Auto-sync new purchases" />
      <Toggle checked={off} onChange={setOff} label="Auto-sync new purchases" />
    </div>
  );
};

/** Disabled state — track dims but keeps the last checked value legible. */
export const Disabled = () => (
  <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
    <Toggle checked={true} onChange={() => {}} label="Show non-comic files" disabled />
    <Toggle checked={false} onChange={() => {}} label="Show non-comic files" disabled />
  </div>
);
