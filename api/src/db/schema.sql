CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    github_id INTEGER NOT NULL UNIQUE,
    github_handle TEXT NOT NULL,
    github_avatar TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_github ON users(github_id);

CREATE TABLE IF NOT EXISTS custom_packages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'My Stack',
    description TEXT DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 1,
    is_public INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_pkg_user ON custom_packages(user_id);

CREATE TABLE IF NOT EXISTS package_tags (
    package_id TEXT NOT NULL REFERENCES custom_packages(id) ON DELETE CASCADE,
    tag_path TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (package_id, tag_path)
);

CREATE TABLE IF NOT EXISTS pinned_skills (
    package_id TEXT NOT NULL REFERENCES custom_packages(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (package_id, skill_id)
);

CREATE TABLE IF NOT EXISTS package_preferences (
    package_id TEXT PRIMARY KEY REFERENCES custom_packages(id) ON DELETE CASCADE,
    min_tier INTEGER DEFAULT 5,
    min_score INTEGER DEFAULT 0,
    verified_only INTEGER DEFAULT 0,
    auto_update INTEGER DEFAULT 1,
    skill_types TEXT DEFAULT 'both'
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    device_code TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    user_id TEXT REFERENCES users(id),
    access_token TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cli_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT DEFAULT '',
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON cli_tokens(token_hash);
