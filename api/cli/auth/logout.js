import { logoutCli, send, withControlPlane } from '../../_lib/flow-control-plane.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to sign out a FLOW device.' });
  return withControlPlane(res, async () => {
    await logoutCli(req);
    res.status(204).end();
  });
}
