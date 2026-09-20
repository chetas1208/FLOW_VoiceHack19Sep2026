import {
  approveCliRequest,
  cliRequestStatus,
  denyCliRequest,
  listDevices,
  requireWebAccount,
  revokeDevice,
  send,
  withControlPlane,
} from '../_lib/flow-control-plane.js';

function segments(req) {
  const path = req.query.path;
  if (Array.isArray(path)) return path;
  if (typeof path === 'string' && path) return [path];
  return [];
}

export default async function handler(req, res) {
  const parts = segments(req);

  if (parts[0] === 'devices' && parts.length === 1) {
    if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to list FLOW devices.' });
    return withControlPlane(res, async () => send(res, 200, await listDevices(req)));
  }

  if (parts[0] === 'devices' && parts.length === 2) {
    if (req.method !== 'DELETE') return send(res, 405, { error: 'method_not_allowed', message: 'Use DELETE to revoke a FLOW device.' });
    return withControlPlane(res, async () => {
      await revokeDevice(req, parts[1]);
      res.status(204).end();
    });
  }

  if (parts[0] === 'cli-requests' && parts.length === 2) {
    if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to inspect a FLOW device request.' });
    return withControlPlane(res, async () => {
      await requireWebAccount(req);
      send(res, 200, await cliRequestStatus(parts[1]));
    });
  }

  if (parts[0] === 'cli-requests' && parts.length === 3 && parts[2] === 'approve') {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to approve a FLOW device.' });
    return withControlPlane(res, async () => send(res, 200, await approveCliRequest(req, parts[1])));
  }

  if (parts[0] === 'cli-requests' && parts.length === 3 && parts[2] === 'deny') {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to deny a FLOW device.' });
    return withControlPlane(res, async () => send(res, 200, await denyCliRequest(req, parts[1])));
  }

  return send(res, 404, { error: 'not_found', message: 'Unknown account route.' });
}
