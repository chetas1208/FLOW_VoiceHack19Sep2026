-- Browser account identity and opaque web sessions. FLOW work-session data
-- remains local; this database stores only identity/control-plane metadata.
create table if not exists flow_users (
  id text primary key,
  email text not null unique,
  display_name text not null,
  password_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists flow_web_sessions (
  id text primary key,
  user_id text not null references flow_users(id) on delete cascade,
  token_hash text not null unique,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz
);
create index if not exists flow_web_sessions_active_idx
  on flow_web_sessions (token_hash, expires_at)
  where revoked_at is null;

-- 001_account_control_plane.sql creates the fuller profile table. Keeping this
-- small compatibility definition makes a fresh account deployment safe even
-- when web-account migration is applied first.
create table if not exists flow_profiles (
  user_id text primary key,
  display_name text,
  timezone text not null default 'UTC',
  preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
