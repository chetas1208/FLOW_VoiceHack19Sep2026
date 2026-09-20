import { cliRequestStatus, requireWebAccount, send, withControlPlane } from '../../../_lib/flow-control-plane.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to inspect a FLOW device request.' });
  return withControlPlane(res, async () => {
    await requireWebAccount(req);
    send(res, 200, await cliRequestStatus(req.query.requestId));
  });
}
