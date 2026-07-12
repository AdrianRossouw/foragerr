import type { ReactNode } from 'react';
import { Modal } from 'foragerr-frontend';

/**
 * Modal's backdrop is `position: fixed`, which would escape its card. A `transform`
 * on the wrapper establishes a containing block for fixed descendants, so the
 * backdrop is clipped to this box instead of the whole capture. Gives an explicit
 * height so the open dialog is fully visible.
 */
const Stage = ({ children, height = 380 }: { children: ReactNode; height?: number }) => (
  <div
    style={{
      position: 'relative',
      height,
      transform: 'translateZ(0)',
      overflow: 'hidden',
      borderRadius: 8,
    }}
  >
    {children}
  </div>
);

const btn = (accent?: boolean): React.CSSProperties => ({
  padding: '6px 14px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid ' + (accent ? 'var(--color-accent)' : 'var(--surface-border)'),
  background: accent ? 'var(--color-accent)' : 'transparent',
  color: accent ? '#0b0b0b' : 'var(--text-primary)',
  font: 'inherit',
  cursor: 'pointer',
});

const field = (label: string, value: string) => (
  <label style={{ display: 'block', marginBottom: 14 }}>
    <div style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)', marginBottom: 4 }}>{label}</div>
    <input
      defaultValue={value}
      style={{
        width: '100%',
        padding: '7px 10px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--surface-border)',
        background: 'var(--surface-card)',
        color: 'var(--text-primary)',
        font: 'inherit',
      }}
    />
  </label>
);

/** Edit-series dialog: header title, a small form body, footer actions. */
export const EditSeries = () => (
  <Stage height={480}>
    <Modal title="Edit series" label="Edit series" onClose={() => {}} footer={
      <>
        <button type="button" style={btn()}>Cancel</button>
        <button type="button" style={btn(true)}>Save</button>
      </>
    }>
      {field('Title', 'Saga')}
      {field('Root folder', '/comics/Saga (2012)')}
      {field('Quality profile', 'Any')}
    </Modal>
  </Stage>
);

/** Delete-confirmation dialog: a destructive action with a danger primary button. */
export const DeleteConfirm = () => (
  <Stage height={300}>
    <Modal title="Delete series" label="Delete series" onClose={() => {}} footer={
      <>
        <button type="button" style={btn()}>Cancel</button>
        <button
          type="button"
          style={{ ...btn(), borderColor: 'var(--color-danger, #e05050)', color: 'var(--color-danger, #e05050)' }}
        >
          Delete
        </button>
      </>
    }>
      <p style={{ margin: 0 }}>
        Remove <strong>Monstress</strong> from the library? Its 52 tracked issues will be
        unmonitored. Files on disk are not deleted.
      </p>
    </Modal>
  </Stage>
);
