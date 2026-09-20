import { expiredCookie, revokeCurrentSession, send } from '../_lib/flow-auth.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST.' });
  try {
    await revokeCurrentSession(req);
    res.setHeader('Set-Cookie', expiredCookie(req));
    return res.status(204).end();
  } catch {
    console.error('account logout failed');
    return send(res, 500, { error: 'internal_error', message: 'Unable to sign out. Try again.' });
  }
}
