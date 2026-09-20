import { currentSession, send } from '../_lib/flow-auth.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET.' });
  try {
    const session = await currentSession(req);
    return session ? send(res, 200, session) : send(res, 401, { error: 'unauthorized', message: 'Sign in required.' });
  } catch {
    console.error('account session lookup failed');
    return send(res, 500, { error: 'internal_error', message: 'Unable to check your session. Try again.' });
  }
}
