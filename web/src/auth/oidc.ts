// Generic OpenID Connect authorization-code + PKCE flow. Only standard endpoints from the issuer's discovery
// document are used, so any compliant IdP (Auth0, Okta, Keycloak, Entra, Google, Cognito, ...) works.
import { config } from '../config';
import { safeReturnTo, type Credentials } from './storage';

const TX_KEY = 'flow.oidc.tx';
const TX_MAX_AGE_MS = 10 * 60 * 1000;

interface Discovery { authorization_endpoint: string; token_endpoint: string; issuer?: string; end_session_endpoint?: string }
let discovery: Promise<Discovery> | null = null;

const isSecure = (url: string) => {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname));
  } catch { return false; }
};

export function b64url(bytes: Uint8Array): string {
  let s = '';
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export const randomString = (bytes = 32) => b64url(crypto.getRandomValues(new Uint8Array(bytes)));

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return b64url(new Uint8Array(digest));
}

async function discover(): Promise<Discovery> {
  const { issuer } = config.oidc;
  if (!issuer || !config.oidc.clientId) throw new Error('OIDC is not configured. Set VITE_OIDC_ISSUER and VITE_OIDC_CLIENT_ID.');
  if (!isSecure(issuer)) throw new Error('The OIDC issuer must use https.');
  discovery ??= fetch(`${issuer}/.well-known/openid-configuration`, { credentials: 'omit' })
    .then((r) => { if (!r.ok) throw new Error('Could not load the identity provider configuration.'); return r.json() as Promise<Discovery>; })
    .then((d) => {
      if (!isSecure(d.authorization_endpoint) || !isSecure(d.token_endpoint)) throw new Error('Identity provider endpoints must use https.');
      return d;
    })
    .catch((e) => { discovery = null; throw e; });
  return discovery;
}

interface Transaction { state: string; nonce: string; verifier: string; returnTo: string; at: number }

export async function beginLogin(returnTo: string): Promise<void> {
  const d = await discover();
  const tx: Transaction = { state: randomString(24), nonce: randomString(24), verifier: randomString(48), returnTo: safeReturnTo(returnTo), at: Date.now() };
  sessionStorage.setItem(TX_KEY, JSON.stringify(tx));
  const params = new URLSearchParams({
    response_type: 'code', client_id: config.oidc.clientId, redirect_uri: config.oidc.redirectUri, scope: config.oidc.scope,
    state: tx.state, nonce: tx.nonce, code_challenge: await challengeFor(tx.verifier), code_challenge_method: 'S256',
  });
  if (config.oidc.audience) params.set('audience', config.oidc.audience);
  window.location.assign(`${d.authorization_endpoint}?${params}`);
}

interface TokenResponse { access_token?: string; id_token?: string; refresh_token?: string; expires_in?: number; error?: string; error_description?: string }

function toCredentials(t: TokenResponse, previousRefresh?: string): Credentials {
  const token = config.oidc.tokenUse === 'id' ? t.id_token : t.access_token;
  if (!token) throw new Error('The identity provider did not return the expected token.');
  const claims = decodeClaims(t.id_token ?? token);
  return {
    token, email: typeof claims?.email === 'string' ? claims.email : undefined,
    expiresAt: t.expires_in ? Date.now() + t.expires_in * 1000 : undefined, refreshToken: t.refresh_token ?? previousRefresh,
  };
}

export function decodeClaims(jwt: string): Record<string, unknown> | null {
  try { return JSON.parse(atob(jwt.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/'))); } catch { return null; }
}

async function tokenRequest(body: Record<string, string>): Promise<TokenResponse> {
  const d = await discover();
  const res = await fetch(d.token_endpoint, {
    method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(body),
  });
  const json = (await res.json().catch(() => ({}))) as TokenResponse;
  if (!res.ok) throw new Error(json.error_description || json.error || 'Sign-in failed.');
  return json;
}

/** Handles the redirect back from the IdP. Returns credentials and where to send the user next. */
export async function completeLogin(search: string): Promise<{ credentials: Credentials; returnTo: string }> {
  const params = new URLSearchParams(search);
  const raw = sessionStorage.getItem(TX_KEY);
  sessionStorage.removeItem(TX_KEY); // single use
  if (params.get('error')) throw new Error(params.get('error_description') || params.get('error') || 'Sign-in was cancelled.');
  if (!raw) throw new Error('This sign-in link has expired. Start again.');
  const tx = JSON.parse(raw) as Transaction;
  if (Date.now() - tx.at > TX_MAX_AGE_MS) throw new Error('This sign-in link has expired. Start again.');
  const code = params.get('code');
  if (!code || params.get('state') !== tx.state) throw new Error('Sign-in could not be verified. Start again.');
  const t = await tokenRequest({
    grant_type: 'authorization_code', code, client_id: config.oidc.clientId, redirect_uri: config.oidc.redirectUri, code_verifier: tx.verifier,
  });
  if (t.id_token) {
    const claims = decodeClaims(t.id_token);
    if (claims?.nonce !== undefined && claims.nonce !== tx.nonce) throw new Error('Sign-in could not be verified. Start again.');
  }
  return { credentials: toCredentials(t), returnTo: tx.returnTo };
}

export async function refreshLogin(refreshToken: string): Promise<Credentials> {
  const t = await tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken, client_id: config.oidc.clientId });
  return toCredentials(t, refreshToken);
}
