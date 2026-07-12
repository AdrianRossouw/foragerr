import { LogoutButton } from 'foragerr-frontend';

/**
 * The header logout control (m8-auth-core): an icon button matching the other
 * whole-app header actions (health, system). Renders on the dark header
 * surface; the mutation only fires on click, so the static render is the
 * resting icon button.
 */
export const Default = () => (
  <div style={{ display: 'inline-flex' }}>
    <LogoutButton />
  </div>
);
