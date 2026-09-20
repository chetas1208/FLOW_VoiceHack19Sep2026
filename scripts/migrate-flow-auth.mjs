import { readFile } from 'node:fs/promises';
import { Client } from 'pg';

const connectionString = process.env.DATABASE_URL;
if (!connectionString) throw new Error('DATABASE_URL is required');

const client = new Client({ connectionString });
const migrations = [
  'services/flow/account/migrations/001_account_control_plane.sql',
  'services/flow/account/migrations/002_web_accounts.sql',
];

await client.connect();
try {
  for (const path of migrations) await client.query(await readFile(path, 'utf8'));
  console.log('FLOW account migrations applied.');
} finally {
  await client.end();
}
