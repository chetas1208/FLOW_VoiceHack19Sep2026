import { apiSegments } from './_lib/api-path.js';
import { handleAccountApi } from './_lib/account-api.js';
import { handleAuthApi } from './_lib/auth-api.js';
import { handleCliApi } from './_lib/cli-api.js';
import { send } from './_lib/flow-auth.js';

export default async function handler(req, res) {
  const parts = apiSegments(req);
  if (!parts.length) return send(res, 404, { error: 'not_found', message: 'Unknown API route.' });

  switch (parts[0]) {
    case 'auth':
      return handleAuthApi(req, res, parts.slice(1));
    case 'account':
      return handleAccountApi(req, res, parts.slice(1));
    case 'cli':
      return handleCliApi(req, res, parts.slice(1));
    default:
      return send(res, 404, { error: 'not_found', message: 'Unknown API route.' });
  }
}
