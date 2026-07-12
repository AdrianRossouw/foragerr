import { FolderScanIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <FolderScanIcon size={18} />
    <FolderScanIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <FolderScanIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>FolderScanIcon</span>
  </div>
);
