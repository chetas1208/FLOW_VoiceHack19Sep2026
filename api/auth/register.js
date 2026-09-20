import { PublicError, createAccount, readJson, send } from '../_lib/flow-auth.js';

export default async function handler(req, res) {
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
}
