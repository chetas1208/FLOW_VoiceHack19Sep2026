import { createHash, createHmac, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import {
  PublicError,
  currentSession,
  database,
  normalizeEmail,
  readJson,
  send,
  tokenHash,
} from './flow-auth.js';

export { send } from './flow-auth.js';

const REQUEST_TTL_SECONDS = 5 * 60;
const ACCESS_TTL_SECONDS = 15 * 60;
const REFRESH_TTL_DAYS = 30;
const DEVICE_ID = /^dev_[A-Za-z0-9_-]{12,100}$/;
const REQUEST_ID = /^car_[A-Za-z0-9_-]{16,100}$/;

function base64url(value) {
  return Buffer.from(value).toString('base64url');
}

function json(value) {
  return base64url(JSON.stringify(value));
}

function signingKey() {
  const value = process.env.FLOW_ACCOUNT_SIGNING_KEY;
  if (!value || value.length < 32) throw new Error('FLOW_ACCOUNT_SIGNING_KEY is not configured securely');
  return value;
}

function signature(value) {
  return createHmac('sha256', signingKey()).update(value).digest('base64url');
}

function safeEqual(left, right) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function accessToken(userId, deviceId) {
  const now = Math.floor(Date.now() / 1000);
  const unsigned = `${json({ alg: 'HS256', typ: 'JWT' })}.${json({
    sub: userId,
    device_id: deviceId,
    scope: 'profile devices heartbeat',
    iat: now,
    exp: now + ACCESS_TTL_SECONDS,
    jti: randomUUID(),
  })}`;
  return `${unsigned}.${signature(unsigned)}`;
}

function accessClaims(value) {
  if (typeof value !== 'string') throw new PublicError(401, 'A valid FLOW device credential is required.');
  const [header, body, actualSignature, ...extra] = value.split('.');
  if (!header || !body || !actualSignature || extra.length || !safeEqual(actualSignature, signature(`${header}.${body}`))) {
    throw new PublicError(401, 'A valid FLOW device credential is required.');
  }
  let claims;
  try { claims = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')); } catch { throw new PublicError(401, 'A valid FLOW device credential is required.'); }
  if (!claims || typeof claims.sub !== 'string' || !DEVICE_ID.test(claims.device_id) || !Number.isSafeInteger(claims.exp) || claims.exp <= Math.floor(Date.now() / 1000)) {
    throw new PublicError(401, 'Your FLOW device credential has expired. Sign in again.');
  }
  return claims;
}

function bearerToken(req) {
  const value = req.headers?.authorization;
  if (typeof value !== 'string' || !value.startsWith('Bearer ')) throw new PublicError(401, 'A valid FLOW device credential is required.');
  return value.slice('Bearer '.length);
}

function sameOrigin(req) {
  const origin = req.headers?.origin;
  if (!origin) return;
  const host = String(req.headers?.['x-forwarded-host'] || req.headers?.host || '').split(',')[0].trim();
  try {
    if (!host || new URL(origin).host !== host) throw new Error('mismatch');
  } catch {
    throw new PublicError(403, 'This request must come from the FLOW app.');
  }
}

function string(value, field, { min = 1, max = 200, pattern } = {}) {
  if (typeof value !== 'string') throw new PublicError(422, `Enter a valid ${field}.`);
  const result = value.trim();
  if (result.length < min || result.length > max || (pattern && !pattern.test(result))) throw new PublicError(422, `Enter a valid ${field}.`);
  return result;
}

function deviceMetadata(value) {
  const source = value && typeof value === 'object' ? value : {};
  const id = string(source.device_id ?? source.id, 'device id', { min: 16, max: 104, pattern: DEVICE_ID });
  return {
    id,
    name: string(source.name ?? 'FLOW device', 'device name', { max: 120 }),
    os: string(source.os ?? 'unknown', 'operating system', { max: 50 }),
    architecture: string(source.architecture ?? 'unknown', 'architecture', { max: 50 }),
    flow_version: string(source.flow_version ?? 'unknown', 'FLOW version', { max: 50 }),
  };
}

function validPkce(verifier, expectedChallenge) {
  if (typeof verifier !== 'string' || verifier.length < 43 || verifier.length > 128 || !/^[A-Za-z0-9_-]+$/.test(verifier)) return false;
  // PKCE in the Python CLI uses SHA-256. Import it lazily here without accepting alternate algorithms.
  const expected = Buffer.from(expectedChallenge);
  const actual = Buffer.from(sha256(verifier));
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

function sha256(value) {
  return createHash('sha256').update(value).digest('base64url');
}

function cleanHealth(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const allowed = new Set(['daemon', 'observer', 'agent', 'intelligence', 'voice', 'model', 'session_id', 'session_status', 'session_goal']);
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    if (allowed.has(key) && typeof item === 'string' && item.length <= 64) result[key] = item;
  }
  return result;
}

function presenceState(health) {
  return Object.values(health).some((value) => /error|degraded|unavailable/i.test(value)) ? 'degraded' : 'online';
}

async function profile(client, user) {
  await client.query(
    'insert into flow_profiles (user_id, display_name) values ($1, $2) on conflict (user_id) do nothing',
    [user.id, user.name],
  );
}

async function issueTokens(client, userId, deviceId, familyId = `fam_${randomUUID().replaceAll('-', '')}`) {
  const refreshToken = `flowr_${randomBytes(32).toString('base64url')}`;
  const expiresAt = new Date(Date.now() + REFRESH_TTL_DAYS * 24 * 60 * 60 * 1000);
  await client.query(
    'insert into flow_device_credentials (token_hash, family_id, user_id, device_id, scopes, expires_at) values ($1, $2, $3, $4, $5, $6)',
    [tokenHash(refreshToken), familyId, userId, deviceId, ['profile', 'devices', 'heartbeat'], expiresAt],
  );
  return { access_token: accessToken(userId, deviceId), refresh_token: refreshToken, token_type: 'Bearer', expires_in: ACCESS_TTL_SECONDS, device_id: deviceId };
}

async function loadRequest(client, id, lock = false) {
  const requestId = string(id, 'authorization request', { min: 20, max: 104, pattern: REQUEST_ID });
  const result = await client.query(
    `select id, user_id, state, code_challenge, device, scopes, status, expires_at from flow_cli_auth_requests where id = $1${lock ? ' for update' : ''}`,
    [requestId],
  );
  const item = result.rows[0];
  if (!item) throw new PublicError(404, 'FLOW could not find this device authorization request.');
  if (item.status === 'pending' && new Date(item.expires_at).getTime() <= Date.now()) {
    await client.query("update flow_cli_auth_requests set status = 'expired' where id = $1 and status = 'pending'", [requestId]);
    item.status = 'expired';
  }
  return item;
}

function publicRequest(item) {
  const device = typeof item.device === 'string' ? JSON.parse(item.device) : item.device;
  return { request_id: item.id, status: item.status, device: { name: device.name, os: device.os, architecture: device.architecture, flow_version: device.flow_version }, expires_at: item.expires_at };
}

export async function withControlPlane(res, work) {
  try {
    await work();
  } catch (error) {
    if (error instanceof PublicError) return send(res, error.status, { error: 'request_error', message: error.message });
    console.error('FLOW control-plane request failed', { name: error?.name, message: error?.message });
    return send(res, 500, { error: 'internal_error', message: 'FLOW could not complete that request.' });
  }
}

export async function requireWebAccount(req) {
  const session = await currentSession(req);
  if (!session) throw new PublicError(401, 'Sign in to your FLOW account first.');
  return session.user;
}

export async function createCliRequest(req) {
  const body = await readJson(req);
  const state = string(body.state, 'request state', { min: 16, max: 200, pattern: /^[A-Za-z0-9_-]+$/ });
  const codeChallenge = string(body.code_challenge, 'PKCE challenge', { min: 43, max: 128, pattern: /^[A-Za-z0-9_-]+$/ });
  const device = deviceMetadata(body.device);
  const id = `car_${randomBytes(24).toString('base64url')}`;
  const expiresAt = new Date(Date.now() + REQUEST_TTL_SECONDS * 1000);
  await database().query(
    "insert into flow_cli_auth_requests (id, state, code_challenge, device, scopes, status, expires_at) values ($1, $2, $3, $4::jsonb, $5, 'pending', $6)",
    [id, state, codeChallenge, JSON.stringify(device), ['profile', 'devices', 'heartbeat'], expiresAt],
  );
  return { request_id: id, state, verification_uri: `/cli/authorize?request=${encodeURIComponent(id)}&state=${encodeURIComponent(state)}`, expires_in: REQUEST_TTL_SECONDS, poll_interval: 2, expires_at: expiresAt };
}

export async function cliRequestStatus(id) {
  const client = await database().connect();
  try { return publicRequest(await loadRequest(client, id)); } finally { client.release(); }
}

export async function approveCliRequest(req, id) {
  sameOrigin(req);
  const user = await requireWebAccount(req);
  const body = await readJson(req);
  const submittedState = string(body.state, 'request state', { min: 16, max: 200, pattern: /^[A-Za-z0-9_-]+$/ });
  const client = await database().connect();
  try {
    await client.query('begin');
    const item = await loadRequest(client, id, true);
    if (item.status !== 'pending') throw new PublicError(409, `This device request is ${item.status}.`);
    if (!safeEqual(item.state, submittedState)) throw new PublicError(422, 'This device request does not match the browser approval.');
    await profile(client, user);
    await client.query("update flow_cli_auth_requests set user_id = $2, status = 'approved', approved_at = now() where id = $1", [item.id, user.id]);
    await client.query('commit');
    return { status: 'approved' };
  } catch (error) {
    await client.query('rollback');
    throw error;
  } finally { client.release(); }
}

export async function denyCliRequest(req, id) {
  sameOrigin(req);
  await requireWebAccount(req);
  const client = await database().connect();
  try {
    const item = await loadRequest(client, id, true);
    if (item.status !== 'pending') throw new PublicError(409, `This device request is ${item.status}.`);
    await client.query("update flow_cli_auth_requests set status = 'denied' where id = $1", [item.id]);
    return { status: 'denied' };
  } finally { client.release(); }
}

export async function exchangeCliToken(req) {
  const body = await readJson(req);
  const client = await database().connect();
  try {
    await client.query('begin');
    const item = await loadRequest(client, body.request_id, true);
    if (item.status === 'pending') throw new PublicError(428, 'Waiting for account approval.');
    if (item.status !== 'approved' || !item.user_id) throw new PublicError(401, `This device request is ${item.status}.`);
    if (!validPkce(body.code_verifier, item.code_challenge)) throw new PublicError(401, 'PKCE verification failed.');
    const device = typeof item.device === 'string' ? JSON.parse(item.device) : item.device;
    const current = await client.query('select user_id, revoked_at from flow_devices where id = $1 for update', [device.id]);
    if (current.rows[0] && current.rows[0].user_id !== item.user_id) throw new PublicError(409, 'This device is already linked to another FLOW account.');
    if (current.rows[0]?.revoked_at) throw new PublicError(401, 'This device was revoked. Run FLOW setup to create a new device identity.');
    await client.query(
      'insert into flow_devices (id, user_id, name, os, architecture, flow_version, last_seen_at) values ($1, $2, $3, $4, $5, $6, now()) on conflict (id) do update set name = excluded.name, os = excluded.os, architecture = excluded.architecture, flow_version = excluded.flow_version, last_seen_at = now()',
      [device.id, item.user_id, device.name, device.os, device.architecture, device.flow_version],
    );
    await client.query(
      "insert into flow_device_presence (device_id, state, last_heartbeat_at, health, active_sessions) values ($1, 'online', now(), $2::jsonb, '{}') on conflict (device_id) do update set state = 'online', last_heartbeat_at = now(), health = excluded.health",
      [device.id, JSON.stringify({ daemon: 'not_running', agent: 'idle', model: 'not_loaded' })],
    );
    const tokens = await issueTokens(client, item.user_id, device.id);
    await client.query("update flow_cli_auth_requests set status = 'consumed', used_at = now() where id = $1", [item.id]);
    await client.query('commit');
    return tokens;
  } catch (error) {
    await client.query('rollback');
    throw error;
  } finally { client.release(); }
}

export async function refreshCliToken(req) {
  const body = await readJson(req);
  const refreshToken = string(body.refresh_token, 'refresh token', { min: 40, max: 300, pattern: /^flowr_[A-Za-z0-9_-]+$/ });
  const client = await database().connect();
  try {
    await client.query('begin');
    const result = await client.query('select family_id, user_id, device_id, rotated_at, revoked_at, expires_at from flow_device_credentials where token_hash = $1 for update', [tokenHash(refreshToken)]);
    const credential = result.rows[0];
    if (!credential || credential.revoked_at || new Date(credential.expires_at).getTime() <= Date.now()) throw new PublicError(401, 'Your FLOW device session has expired. Sign in again.');
    if (credential.rotated_at) {
      await client.query('update flow_device_credentials set revoked_at = now() where family_id = $1 and revoked_at is null', [credential.family_id]);
      throw new PublicError(401, 'Refresh token reuse detected. Sign in again.');
    }
    const device = await client.query('select id from flow_devices where id = $1 and user_id = $2 and revoked_at is null', [credential.device_id, credential.user_id]);
    if (!device.rows[0]) throw new PublicError(401, 'This device is no longer active.');
    await client.query('update flow_device_credentials set rotated_at = now() where token_hash = $1', [tokenHash(refreshToken)]);
    const tokens = await issueTokens(client, credential.user_id, credential.device_id, credential.family_id);
    await client.query('commit');
    return tokens;
  } catch (error) {
    await client.query('rollback');
    throw error;
  } finally { client.release(); }
}

export async function authorizeDevice(req) {
  const claims = accessClaims(bearerToken(req));
  const result = await database().query('select id, user_id from flow_devices where id = $1 and user_id = $2 and revoked_at is null', [claims.device_id, claims.sub]);
  if (!result.rows[0]) throw new PublicError(401, 'This FLOW device is no longer active.');
  return { userId: claims.sub, deviceId: claims.device_id };
}

export async function deviceHeartbeat(req) {
  const identity = await authorizeDevice(req);
  const body = await readJson(req);
  const health = cleanHealth(body.health);
  const sessions = Array.isArray(body.active_sessions) ? body.active_sessions.filter((value) => typeof value === 'string' && value.length <= 120).slice(0, 20) : [];
  const state = presenceState(health);
  await database().query(
    'insert into flow_device_presence (device_id, state, last_heartbeat_at, health, active_sessions) values ($1, $2, now(), $3::jsonb, $4::text[]) on conflict (device_id) do update set state = excluded.state, last_heartbeat_at = now(), health = excluded.health, active_sessions = excluded.active_sessions',
    [identity.deviceId, state, JSON.stringify(health), sessions],
  );
  await database().query('update flow_devices set last_seen_at = now() where id = $1', [identity.deviceId]);
  return { state, device_id: identity.deviceId };
}

export async function cliIdentity(req) {
  const identity = await authorizeDevice(req);
  const result = await database().query('select id, email, display_name from flow_users where id = $1', [identity.userId]);
  const user = result.rows[0];
  if (!user) throw new PublicError(401, 'This FLOW account no longer exists.');
  return { id: user.id, email: normalizeEmail(user.email), name: user.display_name, device_id: identity.deviceId };
}

async function devicesForUser(userId) {
  const result = await database().query(
    "select d.id, d.name, d.os, d.architecture, d.flow_version, d.created_at, d.last_seen_at, d.revoked_at, coalesce(p.health, '{}'::jsonb) as health, p.last_heartbeat_at, coalesce(p.active_sessions, '{}') as active_sessions, case when p.last_heartbeat_at is null or p.last_heartbeat_at < now() - interval '90 seconds' then 'offline' else p.state end as state from flow_devices d left join flow_device_presence p on p.device_id = d.id where d.user_id = $1 order by d.last_seen_at desc nulls last, d.created_at desc",
    [userId],
  );
  return { items: result.rows.map((row) => ({ id: row.id, name: row.name, os: row.os, architecture: row.architecture, flow_version: row.flow_version, created_at: row.created_at, last_seen_at: row.last_seen_at, revoked_at: row.revoked_at, presence: { state: row.state, last_heartbeat_at: row.last_heartbeat_at, health: row.health, active_sessions: Array.isArray(row.active_sessions) ? row.active_sessions : [] } })) };
}

export async function listDevices(req) {
  const user = await requireWebAccount(req);
  return devicesForUser(user.id);
}

export async function listCliDevices(req) {
  const identity = await authorizeDevice(req);
  return devicesForUser(identity.userId);
}

export async function revokeDevice(req, id) {
  sameOrigin(req);
  const user = await requireWebAccount(req);
  const deviceId = string(id, 'device id', { min: 16, max: 104, pattern: DEVICE_ID });
  const result = await database().query('update flow_devices set revoked_at = now() where id = $1 and user_id = $2 and revoked_at is null returning id', [deviceId, user.id]);
  if (!result.rows[0]) throw new PublicError(404, 'FLOW could not find an active device with that id.');
  await database().query('update flow_device_credentials set revoked_at = now() where device_id = $1 and revoked_at is null', [deviceId]);
}

export async function logoutCli(req) {
  const body = await readJson(req);
  const refreshToken = string(body.refresh_token, 'refresh token', { min: 40, max: 300, pattern: /^flowr_[A-Za-z0-9_-]+$/ });
  const result = await database().query('select family_id from flow_device_credentials where token_hash = $1', [tokenHash(refreshToken)]);
  if (result.rows[0]) await database().query('update flow_device_credentials set revoked_at = now() where family_id = $1 and revoked_at is null', [result.rows[0].family_id]);
}
