import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchemaForm } from './SchemaForm';
import type { SchemaField } from './schemaTypes';

/*
 * FRG-UI-008 — the generic schema-form renderer: widget map per field type,
 * write-only secrets, validation surfacing, advanced-field gating. Driven by a
 * synthetic fields[] covering the full backend Field union.
 */

const field = (over: Partial<SchemaField>): SchemaField => ({
  order: 0,
  name: 'field',
  type: 'textbox',
  label: 'Field',
  help: '',
  required: false,
  secret: false,
  advanced: false,
  selectOptions: [],
  ...over,
});

const allTypes: SchemaField[] = [
  field({ order: 0, name: 'host', type: 'textbox', label: 'Host' }),
  field({ order: 1, name: 'port', type: 'number', label: 'Port' }),
  field({ order: 2, name: 'use_ssl', type: 'checkbox', label: 'Use SSL', help: 'Connect over TLS.' }),
  field({
    order: 3,
    name: 'categories',
    type: 'select',
    label: 'Categories',
    selectOptions: [
      { value: 7030, name: 'Books/Comics (7030)' },
      { value: 7000, name: 'Books (7000)' },
    ],
  }),
  field({ order: 4, name: 'api_key', type: 'password', label: 'API Key', secret: true }),
];

describe('FRG-UI-008: schema-form renderer widget map', () => {
  it('FRG-UI-008 — renders text, number, checkbox, select, and password fields via the widget map', () => {
    render(
      <SchemaForm fields={allTypes} values={{}} onChange={() => {}} />,
    );

    expect(screen.getByLabelText('Host')).toHaveAttribute('type', 'text');
    expect(screen.getByLabelText('Port')).toHaveAttribute('type', 'number');
    expect(screen.getByLabelText('Use SSL')).toHaveAttribute('type', 'checkbox');
    expect(screen.getByLabelText('Categories').tagName).toBe('SELECT');
    expect(screen.getByLabelText('Categories')).toHaveAttribute('multiple');
    expect(screen.getByLabelText('API Key')).toHaveAttribute('type', 'password');
  });

  it('FRG-UI-008 — fields render in schema order regardless of array order', () => {
    const shuffled = [allTypes[3], allTypes[0], allTypes[4], allTypes[1], allTypes[2]];
    render(<SchemaForm fields={shuffled} values={{}} onChange={() => {}} />);

    const labels = screen
      .getAllByTestId(/schema-field-/)
      .map((row) => within(row as HTMLElement).getByText(/./, { selector: 'label' }).textContent);
    expect(labels).toEqual(['Host', 'Port', 'Use SSL', 'Categories', 'API Key']);
  });

  it('FRG-UI-008 — multi-select emits typed option values (numbers stay numbers)', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SchemaForm
        fields={[allTypes[3]]}
        values={{ categories: [] }}
        onChange={onChange}
      />,
    );

    await user.selectOptions(screen.getByLabelText('Categories'), ['7030']);
    expect(onChange).toHaveBeenCalledWith('categories', [7030]);
  });

  it('FRG-UI-008 — a scalar field with selectOptions renders a single select preserving typed values', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const priority = field({
      name: 'priority',
      type: 'number',
      label: 'Priority',
      selectOptions: [
        { value: -100, name: 'Default' },
        { value: 1, name: 'High' },
      ],
    });
    render(
      <SchemaForm fields={[priority]} values={{ priority: -100 }} onChange={onChange} />,
    );

    const select = screen.getByLabelText('Priority');
    expect(select.tagName).toBe('SELECT');
    expect(select).not.toHaveAttribute('multiple');
    await user.selectOptions(select, '1');
    expect(onChange).toHaveBeenCalledWith('priority', 1);
  });
});

describe('FRG-UI-008: write-only secret fields', () => {
  it('FRG-UI-008 — a stored secret renders an EMPTY input with placeholder semantics, never the value', () => {
    const { container } = render(
      <SchemaForm
        fields={[allTypes[4]]}
        values={{}}
        onChange={() => {}}
        storedSecrets={new Set(['api_key'])}
      />,
    );

    const input = screen.getByLabelText('API Key') as HTMLInputElement;
    expect(input.value).toBe('');
    expect(input).toHaveAttribute('placeholder', '••••••••');
    expect(screen.getByTestId('secret-hint-api_key')).toHaveTextContent(
      'leave blank to keep',
    );
    // Nothing secret-shaped is ever emitted into the DOM.
    expect(container.innerHTML).not.toMatch(/value="[^"]+"/);
  });

  it('FRG-UI-008 — typing into a secret field emits only the newly typed value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SchemaForm
        fields={[allTypes[4]]}
        values={{}}
        onChange={onChange}
        storedSecrets={new Set(['api_key'])}
      />,
    );

    await user.type(screen.getByLabelText('API Key'), 'k');
    expect(onChange).toHaveBeenCalledWith('api_key', 'k');
  });
});

describe('FRG-UI-008: validation surfacing and advanced gating', () => {
  it('FRG-UI-008 — a field-precise error renders inside that field\'s row', () => {
    render(
      <SchemaForm
        fields={[allTypes[0]]}
        values={{}}
        onChange={() => {}}
        errors={{ host: 'must be an http(s) URL' }}
      />,
    );

    const row = screen.getByTestId('schema-field-host');
    expect(within(row).getByRole('alert')).toHaveTextContent(
      'must be an http(s) URL',
    );
  });

  it('FRG-UI-008 — advanced fields are hidden by default and shown with showAdvanced', () => {
    const advanced = field({ name: 'extra', label: 'Extra', advanced: true });
    const { rerender } = render(
      <SchemaForm fields={[advanced]} values={{}} onChange={() => {}} />,
    );
    expect(screen.queryByLabelText('Extra')).not.toBeInTheDocument();

    rerender(
      <SchemaForm fields={[advanced]} values={{}} onChange={() => {}} showAdvanced />,
    );
    expect(screen.getByLabelText('Extra')).toBeInTheDocument();
  });

  it('FRG-UI-008 — a hidden advanced field carrying an error is force-shown (no silent failures)', () => {
    const advanced = field({ name: 'extra', label: 'Extra', advanced: true });
    render(
      <SchemaForm
        fields={[advanced]}
        values={{}}
        onChange={() => {}}
        errors={{ extra: 'invalid value' }}
      />,
    );
    expect(screen.getByLabelText('Extra')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('invalid value');
  });
});
