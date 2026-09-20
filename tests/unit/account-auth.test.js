import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PublicError, cookieHeader, hashPassword, normalizeEmail, sessionToken,
  validateRegistration, verifyPassword,
} from '../../api/_lib/flow-auth.js';

test('account registration normalizes identity and enforces an adequate password', () => {
  assert.deepEqual(validateRegistration({ name: '  Ada   Lovelace ', email: ' ADA@Example.Test ', password: 'correct-horse-battery-staple' }), {
    name: 'Ada Lovelace', email: 'ada@example.test', password: 'correct-horse-battery-staple',
  });
  assert.throws(() => validateRegistration({ name: 'Ada', email: 'ada@example.test', password: 'short' }), PublicError);
  assert.equal(normalizeEmail('  Person@Example.Test '), 'person@example.test');
});

test('password hashes are salted and verify without retaining the plaintext password', async () => {
  const password = 'correct-horse-battery-staple';
  const first = await hashPassword(password);
  const second = await hashPassword(password);
  assert.notEqual(first, second);
  assert.match(first, /^scrypt\$16384\$8\$1\$/);
  assert.equal(await verifyPassword(password, first), true);
  assert.equal(await verifyPassword('not-the-password', first), false);
});

test('web sessions are parsed from one cookie and use secure attributes in Vercel', () => {
  const prior = process.env.VERCEL;
  process.env.VERCEL = '1';
  try {
    const cookie = cookieHeader('opaque-token', { headers: {} });
    assert.match(cookie, /HttpOnly/);
    assert.match(cookie, /SameSite=Lax/);
    assert.match(cookie, /Secure/);
    assert.equal(sessionToken({ headers: { cookie: `other=1; ${cookie}` } }), 'opaque-token');
  } finally {
    if (prior === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = prior;
  }
});
