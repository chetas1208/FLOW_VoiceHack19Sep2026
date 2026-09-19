// Non-React auth manager: the API client and WebSocket layer call into this singleton.
import { config } from '../config';
import { jwtExpiry, loadCredentials, saveCredentials, type Credentials } from './storage';
import { refreshLogin } from './oidc';

export type AuthStatus = 'signedOut' | 'signedIn';
type Listener = () => void;

const listeners = new Set<Listener>();
let inflight: Promise<string | null> | null = null;
let notice: string | null = null;

const emit = () => listeners.forEach((l) => l());

export const auth = {
  subscribe(l: Listener) { listeners.add(l); return () => { listeners.delete(l); }; },
  credentials(): Credentials | null { return loadCredentials(); },
  status(): AuthStatus { return loadCredentials() ? 'signedIn' : 'signedOut'; },
  email(): string | undefined { return loadCredentials()?.email; },
  notice(): string | null { return notice; },
  clearNotice() { notice = null; },

  getToken(): string | null {
    const c = loadCredentials();
    if (!c) return null;
    const exp = c.expiresAt ?? jwtExpiry(c.token);
    if (exp && exp - 5000 < Date.now()) return null; // treat as expired so callers refresh first
    return c.token;
  },

  setCredentials(c: Credentials) { notice = null; saveCredentials(c); emit(); },

  signOut(reason?: string) {
    saveCredentials(null);
    notice = reason ?? null;
    emit();
  },

  /** Single-flight refresh. Local mode re-runs the dev login for the same email; OIDC uses the refresh token. */
  refresh(): Promise<string | null> {
    inflight ??= (async () => {
      const c = loadCredentials();
      if (!c) return null;
      try {
        if (config.authMode === 'oidc') {
          if (!c.refreshToken) return null;
          const next = await refreshLogin(c.refreshToken);
          saveCredentials({ ...next, email: next.email ?? c.email });
          emit();
          return next.token;
        }
        if (!c.email) return null;
        const res = await fetch(`${config.apiUrl}/v1/dev/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: c.email }) });
        if (!res.ok) return null;
        const body = (await res.json()) as { access_token: string };
        saveCredentials({ token: body.access_token, email: c.email, expiresAt: jwtExpiry(body.access_token) });
        emit();
        return body.access_token;
      } catch { return null; }
    })().finally(() => { inflight = null; });
    return inflight;
  },
};
