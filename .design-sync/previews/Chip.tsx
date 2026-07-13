import { Chip } from 'foragerr-frontend';

/** Every semantic tone, with the realistic library-view labels each maps to. */
export const Tones = () => (
  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
    <Chip>DC Comics</Chip>
    <Chip tone="success">Downloaded</Chip>
    <Chip tone="warning">Wanted</Chip>
    <Chip tone="info">3 vols</Chip>
    <Chip tone="muted">Unmonitored</Chip>
    <Chip tone="overlay">#12</Chip>
    <Chip tone="accent">Monitored</Chip>
  </div>
);

/** Publisher / volume tags as they appear on a series card. */
export const SeriesTags = () => (
  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
    <Chip>Image</Chip>
    <Chip>v2018</Chip>
    <Chip tone="info">Trade</Chip>
  </div>
);
