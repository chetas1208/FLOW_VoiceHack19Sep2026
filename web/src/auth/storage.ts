// Tokens live in memory and sessionStorage only (cleared when the tab closes). Never localStorage, never a cookie.
export interface Credentials {
  token: string;
  email?: string;
  expiresAt?: number; // epoch ms
  refreshToken?: string;
}

const KEY = 'flow.credentials.v1';
let memory: Credentials | null = null;
let hydrated = false;

function ss(): Storage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}

export function loadCredentials(): Credentials | null {
  if (!hydrated) {
    hydrated = true;
    try {
      const raw = ss()?.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Credentials;
        if (parsed && typeof parsed.token === 'string') memory = parsed;
      }
    } catch { /* corrupted or unavailable: start signed out */ }
  }
  return memory;
}

export function saveCredentials(c: Credentials | null): void {
  hydrated = true;
  memory = c;
  try {
    const store = ss();
    if (!store) return;
    if (c) store.setItem(KEY, JSON.stringify(c)); else store.removeItem(KEY);
  } catch { /* memory copy still works */ }
}

export function jwtExpiry(token: string): number | undefined {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : undefined;
  } catch { return undefined; }
}

/** Only same-origin relative paths are allowed as post-login destinations (no open redirects). */
export function safeReturnTo(value: string | null | undefined, fallback = '/'): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\') || /[\u0000-\u001f]/.test(value)) return fallback;
  return value;
}
