import { useState } from 'react';
import { SegmentedControl } from 'foragerr-frontend';

/** The poster-size S/M/L switch from the library Options menu. */
export const PosterSize = () => {
  const [size, setSize] = useState('m');
  return (
    <SegmentedControl
      options={[
        { value: 's', label: 'S' },
        { value: 'm', label: 'M' },
        { value: 'l', label: 'L' },
      ]}
      value={size}
      onChange={setSize}
      ariaLabel="Poster size"
    />
  );
};

/** Word-length labels; the selected segment reads in the accent-selected tint. */
export const WordLabels = () => {
  const [mode, setMode] = useState('missing');
  return (
    <SegmentedControl
      options={[
        { value: 'all', label: 'All' },
        { value: 'missing', label: 'Missing' },
        { value: 'monitored', label: 'Monitored' },
      ]}
      value={mode}
      onChange={setMode}
      ariaLabel="Issue filter"
    />
  );
};
