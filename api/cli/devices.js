import { listCliDevices, send, withControlPlane } from '../../_lib/flow-control-plane.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to list FLOW devices.' });
  return withControlPlane(res, async () => send(res, 200, await listCliDevices(req)));
}
