-- FLOW account control plane. Identity, passwords, sessions and cookies remain
-- owned by Neon Auth/Better Auth. No screenshots, transcripts, source code,
-- observations or session contents belong in these tables.
create table if not exists flow_profiles (
  user_id text primary key,
  display_name text,
  timezone text not null default 'UTC',
  preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists flow_devices (
  id text primary key,
  user_id text not null references flow_profiles(user_id) on delete cascade,
  name text not null,
  os text not null,
  architecture text not null,
  flow_version text not null,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz,
  revoked_at timestamptz
);
create index if not exists flow_devices_user_idx on flow_devices(user_id);

create table if not exists flow_cli_auth_requests (
  id text primary key,
  user_id text references flow_profiles(user_id) on delete cascade,
  state text not null,
  code_challenge text not null,
  device jsonb not null,
  scopes text[] not null,
  status text not null check (status in ('pending','approved','denied','expired','consumed')),
  authorization_code_hash text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  approved_at timestamptz,
  used_at timestamptz
);
create index if not exists flow_cli_auth_requests_expiry_idx on flow_cli_auth_requests(expires_at);

create table if not exists flow_device_credentials (
  token_hash text primary key,
  family_id text not null,
  user_id text not null references flow_profiles(user_id) on delete cascade,
  device_id text not null references flow_devices(id) on delete cascade,
  scopes text[] not null,
  issued_at timestamptz not null default now(),
  expires_at timestamptz not null,
  rotated_at timestamptz,
  revoked_at timestamptz
);
create index if not exists flow_device_credentials_family_idx on flow_device_credentials(family_id);

create table if not exists flow_device_presence (
  device_id text primary key references flow_devices(id) on delete cascade,
  state text not null check (state in ('online','degraded','offline')),
  last_heartbeat_at timestamptz not null,
  health jsonb not null default '{}'::jsonb,
  active_sessions text[] not null default '{}'
);
