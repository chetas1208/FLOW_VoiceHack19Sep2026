import { revokeDevice, send, withControlPlane } from '../../../_lib/flow-control-plane.js';

export default async function handler(req, res) {
  if (req.method !== 'DELETE') return send(res, 405, { error: 'method_not_allowed', message: 'Use DELETE to revoke a FLOW device.' });
  return withControlPlane(res, async () => {
    await revokeDevice(req, req.query.deviceId);
    res.status(204).end();
  });
}
