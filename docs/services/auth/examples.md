# Auth Examples

Copy-paste recipes for every auth feature. All examples assume the app is running at `http://localhost:8000` and was generated with `aegis add-service auth[org]`.

---

## 1. Quick Start

Generate a project, seed test users, and verify login works end to end.

```bash
# Generate project with full auth and database
aegis init my-app --services auth[org] --components database
cd my-app
uv sync && source .venv/bin/activate

# Start all services (PostgreSQL + API)
make serve

# In a second terminal, create test users
my-app auth create-test-user --email "admin@example.com" --password "Admin1234!"
my-app auth create-test-users --count 3 --prefix "user"

# Confirm users exist
my-app auth list-users
```

Register via the API and get a token:

```bash
# Register
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "jane@example.com", "password": "Secret1234!", "full_name": "Jane Doe"}' \
  | python3 -m json.tool

# Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=jane@example.com&password=Secret1234!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token: $TOKEN"

# Verify token works
curl -s http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

Expected `/me` response:

```json
{
    "email": "jane@example.com",
    "full_name": "Jane Doe",
    "is_active": true,
    "is_verified": false,
    "role": "user",
    "id": 1,
    "last_login": "2026-03-30T12:00:00",
    "created_at": "2026-03-30T12:00:00",
    "updated_at": null
}
```

---

## 2. Password Reset Flow

Two-step flow: request a token, then confirm with the new password.

**Step 1, request the reset token:**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/password-reset/request \
  -H "Content-Type: application/json" \
  -d '{"email": "jane@example.com"}' \
  | python3 -m json.tool
```

```json
{
    "detail": "If an account exists, a reset token has been created"
}
```

The response is always 200 regardless of whether the email exists, to prevent user enumeration.

**Step 2, retrieve the token from the database:**

In production you would email this token. During development, query it directly:

```bash
# Connect to the local Postgres instance
psql postgresql://postgres:postgres@localhost:5432/my-app \
  -c "SELECT token, created_at, used FROM password_reset_token ORDER BY created_at DESC LIMIT 1;"
```

```
               token                |       created_at       | used
------------------------------------+------------------------+------
 Xk9mP2qR7vN4wL1jC8dE5fA3bH6oK0nT | 2026-03-30 12:01:00    | f
```

**Step 3, confirm the reset:**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/password-reset/confirm \
  -H "Content-Type: application/json" \
  -d '{"token": "Xk9mP2qR7vN4wL1jC8dE5fA3bH6oK0nT", "new_password": "NewSecret5678!"}' \
  | python3 -m json.tool
```

```json
{
    "detail": "Password has been reset successfully"
}
```

**Step 4, verify login with the new password:**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=jane@example.com&password=NewSecret5678!" \
  | python3 -m json.tool
```

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
}
```

!!! note
    The token is single-use. A second confirm with the same token returns `400 Bad Request: Invalid or expired token`.

---

## 3. Email Verification Flow

A verification token is created automatically on registration. Tokens expire after 24 hours (configurable via `EMAIL_VERIFICATION_EXPIRE_HOURS`).

**Step 1, register (token created automatically):**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "bob@example.com", "password": "Secret1234!", "full_name": "Bob Smith"}' \
  | python3 -m json.tool
```

```json
{
    "email": "bob@example.com",
    "full_name": "Bob Smith",
    "is_active": true,
    "is_verified": false,
    "role": "user",
    "id": 2,
    ...
}
```

Note `"is_verified": false`, the account works immediately but is unverified.

**Step 2, retrieve the verification token from the database:**

```bash
psql postgresql://postgres:postgres@localhost:5432/my-app \
  -c "SELECT token, created_at, used FROM email_verification_token ORDER BY created_at DESC LIMIT 1;"
```

```
               token                |       created_at       | used
------------------------------------+------------------------+------
 mQ3sW7xZ2kR9vN5pL8tA1cE4bD6oH0jY | 2026-03-30 12:05:00    | f
```

**Step 3, verify the email:**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token": "mQ3sW7xZ2kR9vN5pL8tA1cE4bD6oH0jY"}' \
  | python3 -m json.tool
```

```json
{
    "detail": "Email has been verified successfully"
}
```

**Step 4, confirm `is_verified` is now true:**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=bob@example.com&password=Secret1234!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('is_verified:', d['is_verified'])"
```

```
is_verified: True
```

---

## 4. Rate Limiting

The login, register, and password reset endpoints use a sliding window rate limiter. Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header.

**Default limits** (configurable in `.env`):

| Endpoint | Limit | Window |
|----------|:-----:|:------:|
| `POST /auth/token` | 5 requests | 60 seconds |
| `POST /auth/register` | 3 requests | 60 seconds |
| `POST /auth/password-reset/request` | 3 requests | 60 seconds |

**Trigger the login rate limit:**

```bash
for i in {1..6}; do
  echo "Attempt $i:"
  curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/auth/token \
    -d "username=nobody@example.com&password=wrong"
  echo
done
```

```
Attempt 1: 401
Attempt 2: 401
Attempt 3: 401
Attempt 4: 401
Attempt 5: 401
Attempt 6: 429
```

**Full 429 response with headers:**

```bash
curl -v -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=nobody@example.com&password=wrong" 2>&1 | grep -E "HTTP|Retry-After|detail"
```

```
< HTTP/1.1 429 Too Many Requests
< Retry-After: 60
{"detail":"Too many requests. Please try again later."}
```

**Adjust limits in `.env`:**

```bash
RATE_LIMIT_LOGIN_MAX=10
RATE_LIMIT_LOGIN_WINDOW=60
RATE_LIMIT_REGISTER_MAX=5
RATE_LIMIT_REGISTER_WINDOW=60
```

---

## 5. Account Lockout

Accounts lock after 5 consecutive failed login attempts (configurable). The lockout lasts 15 minutes by default, then auto-clears on the next login attempt.

**Trigger lockout with bad passwords:**

```bash
# First create a real account
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "Correct1234!"}' > /dev/null

# Submit 5 wrong passwords
for i in {1..5}; do
  echo "Failed attempt $i:"
  curl -s -X POST http://localhost:8000/api/v1/auth/token \
    -d "username=alice@example.com&password=WrongPass" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(' ', d.get('detail','ok'))"
done
```

```
Failed attempt 1:  Incorrect email or password
Failed attempt 2:  Incorrect email or password
Failed attempt 3:  Incorrect email or password
Failed attempt 4:  Incorrect email or password
Failed attempt 5:  Incorrect email or password
```

**Attempt 6, even with the correct password, account is now locked:**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=alice@example.com&password=Correct1234!" \
  | python3 -m json.tool
```

```json
{
    "detail": "Account temporarily locked due to too many failed login attempts. Please try again later."
}
```

HTTP status is `403 Forbidden`.

**Verify lockout in database:**

```bash
psql postgresql://postgres:postgres@localhost:5432/my-app \
  -c "SELECT email, failed_login_attempts, locked_until FROM \"user\" WHERE email = 'alice@example.com';"
```

```
       email          | failed_login_attempts |       locked_until
----------------------+-----------------------+---------------------------
 alice@example.com   |                     5 | 2026-03-30 12:20:00
```

**Auto-unlock:** After 15 minutes, the next login attempt clears `locked_until` automatically, no manual intervention needed.

**Adjust thresholds in `.env`:**

```bash
ACCOUNT_LOCKOUT_ATTEMPTS=5
ACCOUNT_LOCKOUT_MINUTES=15
```

---

## 6. Logout + Refresh-Token Rotation

`POST /auth/logout` revokes the session in the database and drops both the `aegis_session` and `aegis_refresh` cookies. The session's access tokens stop working on their next request, so a bearer client holding a copy is signed out too, not only the browser.

**Login and capture the access + refresh tokens (use `-c` to persist cookies):**

```bash
curl -s -c cookies.txt -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=jane@example.com&password=NewSecret5678!" \
  | python3 -m json.tool
```

```json
{
    "access_token": "eyJ...",
    "token_type": "bearer"
}
```

`cookies.txt` now holds both `aegis_session` and `aegis_refresh`.

**Rotate the access token mid-session (this is what the frontend does on 401):**

```bash
curl -s -b cookies.txt -c cookies.txt -X POST \
  http://localhost:8000/api/v1/auth/refresh \
  | python3 -m json.tool
```

```json
{
    "access_token": "eyJ...new...",
    "token_type": "bearer"
}
```

The refresh cookie in `cookies.txt` has been rotated — the previous value is revoked server-side.

**Replaying the OLD refresh token returns 401 and revokes the whole family:**

```bash
# Save the rotated refresh, then swap in an old one to simulate replay.
# Anything that calls /refresh with a stale refresh nukes the chain.
curl -s -b old_cookies.txt -X POST http://localhost:8000/api/v1/auth/refresh \
  -o /dev/null -w "%{http_code}\n"
# 401
```

**Logout — refresh row revoked, both cookies cleared:**

```bash
curl -s -b cookies.txt -c cookies.txt -X POST \
  http://localhost:8000/api/v1/auth/logout \
  | python3 -m json.tool
```

```json
{
    "detail": "Logged out"
}
```

**Try to refresh after logout — 401 because the row is revoked:**

```bash
curl -s -b cookies.txt -X POST http://localhost:8000/api/v1/auth/refresh \
  -o /dev/null -w "%{http_code}\n"
# 401
```

!!! info "How an access token is revoked"
    Every access token carries its session's id as a `sid` claim. Each request checks that the session still has a live refresh row (one indexed lookup), so logout, "sign out this device", "sign out everywhere else", a password reset and reuse detection end the session's access tokens at once instead of when they expire. A token without `sid` (minted outside a sign-in, such as a load-test token) lives out its short lifetime. See [Refresh-Token Rotation](index.md#refresh-token-rotation) for the design rationale.

---

## 7. Organization Management

Requires `auth[org]` level. Demonstrates creating an org, adding members, updating roles, and deleting.

**Create an admin user and login:**

```bash
# Promote jane to admin first
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin@example.com&password=Admin1234!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

**Create an organization:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orgs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme-corp", "description": "Main organization"}' \
  | python3 -m json.tool
```

```json
{
    "name": "Acme Corp",
    "slug": "acme-corp",
    "description": "Main organization",
    "is_active": true,
    "id": 1,
    "created_at": "2026-03-30T12:30:00",
    "updated_at": null
}
```

The creator is automatically assigned the `owner` role.

**Add a member directly by user ID:**

```bash
curl -s -X POST "http://localhost:8000/api/v1/orgs/1/members?user_id=2&role=member" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -m json.tool
```

```json
{
    "id": 1,
    "organization_id": 1,
    "user_id": 2,
    "role": "member",
    "joined_at": "2026-03-30T12:31:00"
}
```

**Bulk add members:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orgs/1/members/bulk \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [3, 4, 5], "role": "member"}' \
  | python3 -m json.tool
```

**Update a member's role:**

```bash
curl -s -X PATCH "http://localhost:8000/api/v1/orgs/1/members/2?role=admin" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -m json.tool
```

**List members with full user details:**

```bash
curl -s http://localhost:8000/api/v1/orgs/1/members/details \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -m json.tool
```

```json
[
    {
        "user_id": 1,
        "email": "admin@example.com",
        "full_name": null,
        "role": "owner",
        "joined_at": "2026-03-30T12:30:00"
    },
    {
        "user_id": 2,
        "email": "bob@example.com",
        "full_name": "Bob Smith",
        "role": "admin",
        "joined_at": "2026-03-30T12:31:00"
    }
]
```

**Transfer ownership to another member:**

```bash
# body.user_id is the new owner's user ID
curl -s -X POST http://localhost:8000/api/v1/orgs/1/transfer-ownership \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2}' \
  | python3 -m json.tool
```

```json
{
    "detail": "Ownership transferred"
}
```

Only the current `owner` can call this endpoint.

---

## 8. Invite Flow

Two scenarios: inviting an existing user (added immediately) and inviting a new user (pending until they register).

### Invite an Existing User

The user is added to the org instantly, no token acceptance required.

```bash
# bob@example.com already has an account (user_id: 2)
curl -s -X POST http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "bob@example.com", "role": "member"}' \
  | python3 -m json.tool
```

```json
{
    "id": 1,
    "organization_id": 1,
    "email": "bob@example.com",
    "role": "member",
    "status": "accepted",
    "token": "...",
    "created_at": "2026-03-30T12:35:00"
}
```

Note `"status": "accepted"`, membership was created immediately.

### Invite a New User (Pending)

The user doesn't have an account yet. A pending invite is stored and resolved automatically when they register.

**Step 1, create the pending invite:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "newcomer@example.com", "role": "member"}' \
  | python3 -m json.tool
```

```json
{
    "id": 2,
    "organization_id": 1,
    "email": "newcomer@example.com",
    "role": "member",
    "status": "pending",
    "token": "eR7tY2uI9oP4aS1dF6gH3jK8lZ5xCvBn",
    "created_at": "2026-03-30T12:36:00"
}
```

**Step 2, check pending invites:**

```bash
curl -s http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -m json.tool
```

**Step 3a, newcomer registers (auto-joins the org):**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "newcomer@example.com", "password": "Welcome1234!"}' \
  | python3 -m json.tool
```

The `accept_pending_invites` hook fires automatically during registration. The invite status changes to `accepted` and the user is a member immediately.

**Step 3b (alternative), accept invite explicitly by token:**

Use this when `INVITE_ACCEPTANCE_MODE=token` or when you want a registered user to explicitly accept.

```bash
NEWCOMER_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=newcomer@example.com&password=Welcome1234!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/api/v1/auth/accept-invite \
  -H "Authorization: Bearer $NEWCOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token": "eR7tY2uI9oP4aS1dF6gH3jK8lZ5xCvBn"}' \
  | python3 -m json.tool
```

```json
{
    "id": 2,
    "organization_id": 1,
    "email": "newcomer@example.com",
    "role": "member",
    "status": "accepted",
    "token": "eR7tY2uI9oP4aS1dF6gH3jK8lZ5xCvBn",
    "created_at": "2026-03-30T12:36:00"
}
```

!!! note
    In the default `email` mode, the authenticated user's email must match the invite email. In `token` mode, any authenticated user can accept any valid token.

---

## 9. Audit Logging

Every significant auth action emits a structured JSON log event. Events flow through Python's standard `logging` module and appear in the application logs.

**Example log output:**

```
INFO     audit:audit.py:18 {"event_type": "auth.user_registered", "actor_email": "jane@example.com", "target_type": "user", "target_id": 1, "timestamp": "2026-03-30T12:00:00"}
INFO     audit:audit.py:18 {"event_type": "auth.login_success", "actor_email": "jane@example.com", "actor_id": 1, "ip_address": "127.0.0.1", "timestamp": "2026-03-30T12:00:05"}
INFO     audit:audit.py:18 {"event_type": "auth.logout", "actor_id": 1, "timestamp": "2026-03-30T12:45:00"}
INFO     audit:audit.py:18 {"event_type": "auth.account_locked", "actor_email": "alice@example.com", "timestamp": "2026-03-30T13:00:00"}
INFO     audit:audit.py:18 {"event_type": "auth.org_created", "actor_id": 1, "target_type": "org", "target_id": 1, "timestamp": "2026-03-30T12:30:00"}
INFO     audit:audit.py:18 {"event_type": "auth.member_added", "actor_id": 1, "org_id": 1, "target_type": "user", "target_id": 2, "timestamp": "2026-03-30T12:31:00"}
INFO     audit:audit.py:18 {"event_type": "auth.invite_created", "actor_id": 1, "org_id": 1, "detail": "newcomer@example.com", "timestamp": "2026-03-30T12:36:00"}
```

**Tail logs during development:**

```bash
# When running via make serve, logs appear in the docker-compose output.
# Filter for audit events only:
docker compose logs -f backend | grep '"event_type"'
```

**Emit custom audit events from your own code:**

```python
from app.core.audit import AuditEmitter

audit = AuditEmitter()
await audit.emit("myfeature.action_taken", actor_id=user.id, detail="extra context")
```

**Full event reference:**

| Event | Fired When |
|-------|------------|
| `auth.user_registered` | New user registers |
| `auth.login_success` | Successful login |
| `auth.login_failed` | Bad credentials supplied |
| `auth.login_locked` | Login attempt on a locked account |
| `auth.logout` | Token revoked via logout |
| `auth.password_reset_requested` | Reset token created |
| `auth.password_reset_confirmed` | Password changed via reset token |
| `auth.email_verified` | Email verification token accepted |
| `auth.user_updated` | User profile updated |
| `auth.user_activated` | User re-activated by admin |
| `auth.user_deactivated` | User deactivated by admin |
| `auth.user_deleted` | User permanently deleted |
| `auth.org_created` | Organization created |
| `auth.org_updated` | Organization updated |
| `auth.org_deleted` | Organization deleted |
| `auth.org_ownership_transferred` | Ownership transferred to new owner |
| `auth.member_added` | Member added to org |
| `auth.member_removed` | Member removed from org |
| `auth.member_role_updated` | Member's org role changed |
| `auth.members_bulk_added` | Multiple members added at once |
| `auth.invite_created` | Invite sent to email |
| `auth.invite_accepted` | Invite accepted by user |

---

**Next Steps:**

- **[Auth Levels](levels.md)** - Feature comparison across Basic / RBAC / Org
- **[API Reference](api.md)** - Complete endpoint documentation
- **[CLI Commands](cli.md)** - User management from the command line
