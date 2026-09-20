import {
  PublicError,
  createAccount,
  currentSession,
  expiredCookie,
  readJson,
  revokeCurrentSession,
  send,
  signIn,
} from '../_lib/flow-auth.js';

function action(req) {
  const path = req.query.path;
  if (Array.isArray(path)) return path[0] ?? '';
  return typeof path === 'string' ? path : '';
}

export default async function handler(req, res) {
  switch (action(req)) {
    case 'login':
      if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST.' });
      try {
        const result = await signIn(await readJson(req), req);
        res.setHeader('Set-Cookie', result.session.cookie);
        return send(res, 200, { user: result.user, expiresAt: result.session.expiresAt.toISOString() });
      } catch (error) {
        if (error instanceof PublicError) return send(res, error.status, { error: 'account_error', message: error.message });
        console.error('account sign-in failed');
        return send(res, 500, { error: 'internal_error', message: 'Unable to sign in. Try again.' });
      }
    case 'logout':
      if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST.' });
      try {
        await revokeCurrentSession(req);
        res.setHeader('Set-Cookie', expiredCookie(req));
        return res.status(204).end();
      } catch {
        console.error('account logout failed');
        return send(res, 500, { error: 'internal_error', message: 'Unable to sign out. Try again.' });
      }
    case 'register':
      if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST.' });
      try {
        const result = await createAccount(await readJson(req), req);
        res.setHeader('Set-Cookie', result.session.cookie);
        return send(res, 201, { user: result.user, expiresAt: result.session.expiresAt.toISOString() });
      } catch (error) {
        if (error instanceof PublicError) return send(res, error.status, { error: 'account_error', message: error.message });
        console.error('account registration failed');
        return send(res, 500, { error: 'internal_error', message: 'Unable to create your account. Try again.' });
      }
    case 'session':
      if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET.' });
      try {
        const session = await currentSession(req);
        return session ? send(res, 200, session) : send(res, 401, { error: 'unauthorized', message: 'Sign in required.' });
      } catch {
        console.error('account session lookup failed');
        return send(res, 500, { error: 'internal_error', message: 'Unable to check your session. Try again.' });
      }
    default:
      return send(res, 404, { error: 'not_found', message: 'Unknown auth route.' });
  }
}
