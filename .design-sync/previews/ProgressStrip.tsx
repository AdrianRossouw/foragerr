import { ProgressStrip } from 'foragerr-frontend';

/** The three sizing variants: poster-card footer, overview row, dense table cell. */
export const Variants = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: 260 }}>
    <ProgressStrip have={14} total={22} variant="strip" />
    <ProgressStrip have={14} total={22} variant="bar" />
    <ProgressStrip have={14} total={22} variant="mini" />
  </div>
);

/** Complete (green) vs. incomplete (red-tinted track) coloring. */
export const CompleteVsIncomplete = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: 260 }}>
    <ProgressStrip have={36} total={36} variant="bar" />
    <ProgressStrip have={9} total={36} variant="bar" />
    <ProgressStrip have={5} total={30} monitored={false} variant="bar" />
  </div>
);

/** Percent readout alongside (or instead of) the raw count. */
export const CountAndPercent = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: 260 }}>
    <ProgressStrip have={18} total={24} showCount showPercent variant="bar" />
    <ProgressStrip have={18} total={24} showCount={false} showPercent variant="bar" />
  </div>
);
