-- Migration: Migrate from legacy telegram_api_token to secure TelegramToken system
-- Created: 2025-11-20
--
-- SECURITY IMPROVEMENTS:
-- - Replaces unlimited-lifetime tokens with 90-day expiration
-- - Adds scope-based permissions (read, write, admin)
-- - Enables token revocation without changing user password
-- - Adds audit trail (created_at, last_used_at, revoked_at)
--
-- MIGRATION STEPS:
-- 1. Create telegram_tokens table
-- 2. Migrate existing telegram_api_token values to new table
-- 3. Remove telegram_api_token column from users table
--
-- IMPORTANT: This is a breaking change. All existing Telegram integrations
-- will need to regenerate tokens using /telegram/generate-token endpoint.

BEGIN;

-- Step 1: Create telegram_tokens table
CREATE TABLE IF NOT EXISTS telegram_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Token value (cryptographically secure random string)
    token VARCHAR(64) NOT NULL UNIQUE,

    -- Scope defines what this token can access
    -- Possible values: 'read', 'write', 'admin', 'read,write', etc.
    scope VARCHAR(100) NOT NULL DEFAULT 'read',

    -- Token lifecycle
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    expires_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP,

    -- Revocation support
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMP,
    revoked_reason VARCHAR(255),

    -- Optional: Device/client tracking
    device_name VARCHAR(100),
    user_agent VARCHAR(255)
);

-- Create indexes for performance
CREATE INDEX idx_telegram_tokens_token ON telegram_tokens(token);
CREATE INDEX idx_telegram_tokens_user_id ON telegram_tokens(user_id);
CREATE INDEX idx_telegram_tokens_revoked ON telegram_tokens(revoked);
CREATE INDEX idx_telegram_tokens_expires_at ON telegram_tokens(expires_at);

-- Step 2: Migrate existing telegram_api_token values to new table
-- Convert old tokens to new tokens with:
-- - 90-day expiration from now
-- - 'read,write' scope (matching old behavior)
-- - Device name 'Migrated from legacy system'
INSERT INTO telegram_tokens (user_id, token, scope, created_at, expires_at, revoked, device_name)
SELECT
    id,
    telegram_api_token,
    'read,write',
    NOW() AT TIME ZONE 'utc',
    (NOW() AT TIME ZONE 'utc') + INTERVAL '90 days',
    FALSE,
    'Migrated from legacy system'
FROM users
WHERE telegram_api_token IS NOT NULL
ON CONFLICT (token) DO NOTHING;  -- Skip if token already exists

-- Step 3: Drop old telegram_api_token column and index
DROP INDEX IF EXISTS idx_user_telegram_token;
ALTER TABLE users DROP COLUMN IF EXISTS telegram_api_token;

COMMIT;

-- Verification queries (run after migration):
-- SELECT COUNT(*) FROM telegram_tokens;
-- SELECT token_preview, scope, expires_at, device_name FROM telegram_tokens LIMIT 10;
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'telegram_api_token';
