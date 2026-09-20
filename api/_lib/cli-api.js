import {
  cliIdentity,
  cliRequestStatus,
  createCliRequest,
  deviceHeartbeat,
  exchangeCliToken,
  listCliDevices,
  logoutCli,
  refreshCliToken,
  send,
  withControlPlane,
} from './flow-control-plane.js';

export async function handleCliApi(req, res, parts) {
  if (parts.length === 1 && parts[0] === 'me') {
    if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to inspect the FLOW device account.' });
    return withControlPlane(res, async () => send(res, 200, await cliIdentity(req)));
  }

  if (parts.length === 1 && parts[0] === 'devices') {
    if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to list FLOW devices.' });
    return withControlPlane(res, async () => send(res, 200, await listCliDevices(req)));
  }

  if (parts.length === 1 && parts[0] === 'heartbeat') {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to send FLOW device health.' });
    return withControlPlane(res, async () => send(res, 200, await deviceHeartbeat(req)));
  }

  if (parts[0] === 'auth' && parts[1] === 'token' && parts.length === 2) {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to exchange a FLOW device login.' });
    return withControlPlane(res, async () => send(res, 200, await exchangeCliToken(req)));
  }

  if (parts[0] === 'auth' && parts[1] === 'logout' && parts.length === 2) {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to sign out a FLOW device.' });
    return withControlPlane(res, async () => {
      await logoutCli(req);
      res.status(204).end();
    });
  }

  if (parts[0] === 'auth' && parts[1] === 'refresh' && parts.length === 2) {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to refresh a FLOW device login.' });
    return withControlPlane(res, async () => send(res, 200, await refreshCliToken(req)));
  }

  if (parts[0] === 'auth' && parts[1] === 'requests' && parts.length === 2) {
    if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed', message: 'Use POST to begin a FLOW device login.' });
    return withControlPlane(res, async () => send(res, 201, await createCliRequest(req)));
  }

  if (parts[0] === 'auth' && parts[1] === 'requests' && parts.length === 3) {
    if (req.method !== 'GET') return send(res, 405, { error: 'method_not_allowed', message: 'Use GET to check a FLOW device login.' });
    return withControlPlane(res, async () => send(res, 200, await cliRequestStatus(parts[2])));
  }

  return send(res, 404, { error: 'not_found', message: 'Unknown CLI route.' });
}
