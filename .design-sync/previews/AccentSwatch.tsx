import { AccentSwatch } from 'foragerr-frontend';

/** Default accent swatch — resolves `--color-accent` from the document root at render. */
export const Default = () => <AccentSwatch />;

/** Custom label, same token-driven resolution. */
export const CustomLabel = () => <AccentSwatch label="brand accent" />;
