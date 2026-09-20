import { deviceHeartbeat, send, withControlPlane } from '../../_lib/flow-control-plane.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to send FLOW device health.' });
  return withControlPlane(res, async () => send(res, 200, await deviceHeartbeat(req)));
}
