import { createHash, randomBytes, randomUUID, scrypt, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
import { Pool } from 'pg';

const scryptAsync = promisify(scrypt);
const SCRYPT_N = 16_384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const SCRYPT_LENGTH = 64;
const SESSION_TTL_DAYS = Number.parseInt(process.env.FLOW_SESSION_TTL_DAYS ?? '30', 10);

let pool;

export class PublicError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function database() {
  if (!pool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) throw new Error('DATABASE_URL is not configured');
    pool = new Pool({ connectionString, max: 1, connectionTimeoutMillis: 5_000, idleTimeoutMillis: 10_000 });
  }
  return pool;
}

export function normalizeEmail(value) {
  if (typeof value !== 'string') throw new PublicError(422, 'Enter a valid email address.');
  const email = value.trim().toLowerCase();
  if (!email || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new PublicError(422, 'Enter a valid email address.');
  }
  return email;
}

export function validateRegistration(payload) {
  const name = typeof payload?.name === 'string' ? payload.name.trim().replace(/\s+/g, ' ') : '';
  if (!name || name.length > 120) throw new PublicError(422, 'Enter your name.');
  const password = typeof payload?.password === 'string' ? payload.password : '';
  if (password.length < 12) throw new PublicError(422, 'Use a password with at least 12 characters.');
  if (password.length > 1_024) throw new PublicError(422, 'Use a shorter password.');
  return { name, email: normalizeEmail(payload?.email), password };
}

export function validateLogin(payload) {
  const password = typeof payload?.password === 'string' ? payload.password : '';
  if (!password || password.length > 1_024) throw new PublicError(401, 'The email or password is incorrect.');
  return { email: normalizeEmail(payload?.email), password };
}

export async function hashPassword(password) {
  const salt = randomBytes(16);
  const digest = await scryptAsync(password, salt, SCRYPT_LENGTH, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P, maxmem: 64 * 1024 * 1024 });
  return ['scrypt', SCRYPT_N, SCRYPT_R, SCRYPT_P, salt.toString('base64url'), Buffer.from(digest).toString('base64url')].join('$');
}

export async function verifyPassword(password, encoded) {
  const [algorithm, n, r, p, encodedSalt, encodedDigest] = String(encoded).split('$');
  if (algorithm !== 'scrypt' || !encodedSalt || !encodedDigest) return false;
  const parsed = [n, r, p].map(Number);
  if (parsed.some((value) => !Number.isSafeInteger(value) || value < 1)) return false;
  const expected = Buffer.from(encodedDigest, 'base64url');
  if (expected.length !== SCRYPT_LENGTH) return false;
  const actual = Buffer.from(await scryptAsync(password, Buffer.from(encodedSalt, 'base64url'), expected.length, { N: parsed[0], r: parsed[1], p: parsed[2], maxmem: 64 * 1024 * 1024 }));
  return timingSafeEqual(actual, expected);
}

export function tokenHash(value) {
  return createHash('sha256').update(value).digest('hex');
}

function sessionExpiry() {
  if (!Number.isSafeInteger(SESSION_TTL_DAYS) || SESSION_TTL_DAYS < 1 || SESSION_TTL_DAYS > 90) throw new Error('FLOW_SESSION_TTL_DAYS must be between 1 and 90');
  return new Date(Date.now() + SESSION_TTL_DAYS * 24 * 60 * 60 * 1000);
}

function secureRequest(req) {
  return process.env.VERCEL === '1' || req.headers?.['x-forwarded-proto'] === 'https';
}

export function cookieHeader(token, req, maxAge = SESSION_TTL_DAYS * 24 * 60 * 60) {
  return `flow_session=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secureRequest(req) ? '; Secure' : ''}`;
}

export function expiredCookie(req) {
  return `${cookieHeader('', req, 0)}; Expires=Thu, 01 Jan 1970 00:00:00 GMT`;
}

export function sessionToken(req) {
  const value = req.headers?.cookie ?? '';
  const item = value.split(';').map((part) => part.trim()).find((part) => part.startsWith('flow_session='));
  return item ? item.slice('flow_session='.length) : null;
}

export async function readJson(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') {
    try { return JSON.parse(req.body); } catch { throw new PublicError(400, 'Request body must be valid JSON.'); }
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 8_192) throw new PublicError(413, 'Request body is too large.');
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new PublicError(400, 'Request body must be valid JSON.'); }
}

export function send(res, status, body) {
  res.status(status).setHeader('Content-Type', 'application/json; charset=utf-8').send(JSON.stringify(body));
}

export async function createAccount(payload, req) {
  const { name, email, password } = validateRegistration(payload);
  const client = await database().connect();
  try {
    await client.query('BEGIN');
    const result = await client.query(
      'insert into flow_users (id, email, display_name, password_hash) values ($1, $2, $3, $4) on conflict (email) do nothing returning id, email, display_name',
      [`usr_${randomUUID().replaceAll('-', '')}`, email, name, await hashPassword(password)],
    );
    const user = result.rows[0];
    if (!user) throw new PublicError(409, 'An account already exists for that email. Sign in instead.');
    await client.query('insert into flow_profiles (user_id, display_name) values ($1, $2) on conflict (user_id) do nothing', [user.id, user.display_name]);
    const session = await createSession(client, user.id, req);
    await client.query('COMMIT');
    return { user: publicUser(user), session };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

export async function signIn(payload, req) {
  const { email, password } = validateLogin(payload);
  const result = await database().query('select id, email, display_name, password_hash from flow_users where email = $1 limit 1', [email]);
  const user = result.rows[0];
  if (!user || !(await verifyPassword(password, user.password_hash))) throw new PublicError(401, 'The email or password is incorrect.');
  const session = await createSession(database(), user.id, req);
  return { user: publicUser(user), session };
}

async function createSession(client, userId, req) {
  const token = randomBytes(32).toString('base64url');
  const expiresAt = sessionExpiry();
  await client.query('insert into flow_web_sessions (id, user_id, token_hash, expires_at) values ($1, $2, $3, $4)', [`ws_${randomUUID().replaceAll('-', '')}`, userId, tokenHash(token), expiresAt]);
  return { token, cookie: cookieHeader(token, req), expiresAt };
}

export async function currentSession(req) {
  const token = sessionToken(req);
  if (!token) return null;
  const result = await database().query(
    'select u.id, u.email, u.display_name, (select count(*)::int from flow_devices d where d.user_id = u.id and d.revoked_at is null) as device_count from flow_web_sessions s join flow_users u on u.id = s.user_id where s.token_hash = $1 and s.revoked_at is null and s.expires_at > now() limit 1',
    [tokenHash(token)],
  );
  const user = result.rows[0];
  if (!user) return null;
  void database().query('update flow_web_sessions set last_seen_at = now() where token_hash = $1', [tokenHash(token)]).catch(() => undefined);
  return { user: publicUser(user), deviceCount: user.device_count };
}

export async function revokeCurrentSession(req) {
  const token = sessionToken(req);
  if (token) await database().query('update flow_web_sessions set revoked_at = now() where token_hash = $1 and revoked_at is null', [tokenHash(token)]);
}

function publicUser(user) {
  return { id: user.id, email: user.email, name: user.display_name };
}
