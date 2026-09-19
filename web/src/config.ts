const env = import.meta.env;

const trim = (v: string | undefined) => (v ?? '').trim();

export const config = {
  apiUrl: trim(env.VITE_API_URL).replace(/\/+$/, '') || 'http://127.0.0.1:8080',
  authMode: (trim(env.VITE_AUTH_MODE) === 'oidc' ? 'oidc' : 'local') as 'local' | 'oidc',
  oidc: {
    issuer: trim(env.VITE_OIDC_ISSUER).replace(/\/+$/, ''),
    clientId: trim(env.VITE_OIDC_CLIENT_ID),
    scope: trim(env.VITE_OIDC_SCOPE) || 'openid email profile',
    audience: trim(env.VITE_OIDC_AUDIENCE),
    redirectUri: trim(env.VITE_OIDC_REDIRECT_URI) || (typeof window !== 'undefined' ? `${window.location.origin}/auth/callback` : ''),
    tokenUse: (trim(env.VITE_OIDC_TOKEN_USE) === 'id' ? 'id' : 'access') as 'access' | 'id',
  },
};
