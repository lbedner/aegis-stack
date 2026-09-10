# Auth Levels

Aegis Stack's authentication service supports three progressive levels. Start with basic JWT auth and upgrade as your needs grow.

## Choosing Your Level

<div class="grid cards" markdown>

-   **Basic**

    ---

    Registration, login, JWT tokens, password reset, email verification, rate limiting, account lockout, audit logging, token revocation.

    ```bash
    aegis add-service auth
    ```

-   **RBAC**

    ---

    Everything in Basic + role-based access control with `require_role()`, role constants, and admin/moderator permissions.

    ```bash
    aegis add-service auth[rbac]
    ```

-   **Organization**

    ---

    Everything in RBAC + multi-tenant organizations, membership management, invites, ownership transfer, and bulk operations.

    ```bash
    aegis add-service auth[org]
    ```

</div>

## Level Comparison

| Feature | Basic | RBAC | Org |
|---------|:-----:|:----:|:---:|
| User registration & login | :material-check: | :material-check: | :material-check: |
| JWT token authentication | :material-check: | :material-check: | :material-check: |
| Password hashing (bcrypt) | :material-check: | :material-check: | :material-check: |
| Password reset (token-based) | :material-check: | :material-check: | :material-check: |
| Email verification | :material-check: | :material-check: | :material-check: |
| Rate limiting (sliding window) | :material-check: | :material-check: | :material-check: |
| Account lockout | :material-check: | :material-check: | :material-check: |
| Token revocation / logout | :material-check: | :material-check: | :material-check: |
| Audit logging | :material-check: | :material-check: | :material-check: |
| Profile security (self-or-admin) | :material-check: | :material-check: | :material-check: |
| Email normalization | :material-check: | :material-check: | :material-check: |
| Dev mode (bypass auth) | :material-check: | :material-check: | :material-check: |
| Protected routes | :material-check: | :material-check: | :material-check: |
| Dashboard user management tab | :material-check: | :material-check: | :material-check: |
| Role field on user model | | :material-check: | :material-check: |
| `require_role()` endpoint protection | | :material-check: | :material-check: |
| Role constants (admin, moderator, user) | | :material-check: | :material-check: |
| Moderator permissions (list users) | | :material-check: | :material-check: |
| Organization CRUD | | | :material-check: |
| Membership management | | | :material-check: |
| Bulk add members | | | :material-check: |
| Member details with user info | | | :material-check: |
| Ownership transfer | | | :material-check: |
| Invite by email | | | :material-check: |
| Token-based invite acceptance | | | :material-check: |
| Org role hierarchy (owner/admin/member) | | | :material-check: |
| Dashboard organizations tab | | | :material-check: |
| Cascade delete (org/user cleanup) | | | :material-check: |

---

## Basic Level (All Levels)

Every auth level includes the full set of features below. These form the security foundation of every Aegis project.

### User Registration & Login

Users register with email and password, then authenticate via `POST /auth/token` to receive a JWT. The JWT is passed as a `Bearer` token in the `Authorization` header for all protected endpoints.

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "SecurePass123!", "full_name": "Jane Doe"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "user@example.com", "password": "SecurePass123!"}'
```

### Password Hashing

Passwords are hashed using **bcrypt** with automatic 72-byte truncation. Bcrypt silently ignores bytes beyond 72, so Aegis truncates before hashing to ensure consistent behavior across implementations.

### Password Reset

A two-step flow using single-use tokens:

1. **Request a reset token**, `POST /auth/password-reset/request` with the user's email. A token is generated with a configurable expiry (default: 60 minutes).
2. **Confirm the reset**, `POST /auth/password-reset/confirm` with the token and new password. The token is invalidated after use.

```bash
# Request reset
curl -X POST http://localhost:8000/api/v1/auth/password-reset/request \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'

# Confirm reset
curl -X POST http://localhost:8000/api/v1/auth/password-reset/confirm \
  -H "Content-Type: application/json" \
  -d '{"token": "reset-token-here", "new_password": "NewSecurePass456!"}'
```

!!! note
    The request endpoint always returns 200 regardless of whether the email exists, to prevent user enumeration.

### Email Verification

A verification token is created automatically on registration. Users verify by submitting the token to `POST /auth/verify-email`. Tokens expire after 24 hours by default.

```bash
curl -X POST http://localhost:8000/api/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token": "verification-token-here"}'
```

### Rate Limiting

In-memory sliding window rate limiter protects sensitive endpoints from abuse:

| Endpoint | Max Requests | Window |
|----------|:----------:|:------:|
| Login (`/auth/token`) | 5 | 1 minute |
| Register (`/auth/register`) | 3 | 1 minute |
| Password Reset (`/auth/password-reset/request`) | 3 | 1 minute |

When the limit is exceeded, the server returns **429 Too Many Requests** with a `Retry-After` header indicating how many seconds to wait.

### Account Lockout

Protects against brute-force attacks by locking accounts after repeated failed login attempts:

- **Threshold**: 5 failed attempts (configurable via `ACCOUNT_LOCKOUT_ATTEMPTS`)
- **Duration**: 15 minutes auto-unlock (configurable via `ACCOUNT_LOCKOUT_MINUTES`)
- **Reset**: Successful login resets the failure counter

!!! warning
    Locked accounts cannot authenticate even with the correct password until the lockout period expires.

### Token Revocation / Logout

`POST /auth/logout` revokes the current refresh token (DB-backed) and drops both the `aegis_session` and `aegis_refresh` cookies. The short-lived access JWT (~15 min default) is left to expire naturally — there's no stateful blacklist.

For mid-session token rotation, see [Refresh-Token Rotation](index.md#refresh-token-rotation): the frontend `APIClient` transparently calls `POST /auth/refresh` on any 401 and retries the original request, so users stay signed in across days without ever seeing a redirect to `/login`.

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Audit Logging

A generic `AuditEmitter` (located in `app/core/audit.py`) emits structured JSON events via Python's standard logging. Events are domain-prefixed (e.g., `auth.login_success`) and the emitter is injectable via dependency injection.

```python
from app.core.audit import AuditEmitter

audit = AuditEmitter()
await audit.emit("auth.login_success", user_id=user.id, ip="192.168.1.1")
```

See the [Audit Events Reference](#audit-events-reference) for a complete list of events.

### Profile Security

`PATCH /auth/users/{id}` is protected so that only the user themselves or an admin can update a profile. Attempting to update another user's profile without admin privileges returns **403 Forbidden**.

### Email Normalization

All emails are stored in lowercase and matched case-insensitively. `User@Example.COM` and `user@example.com` are treated as the same account.

### Dev Mode

When `AUTH_ENABLED=false`, all protected endpoints return a configurable dev user without requiring authentication. The dev user's role is controlled by the `DEV_USER_ROLE` setting (default: `"user"`).

!!! tip
    Dev mode is useful for frontend development and testing without running the full auth flow. Never use this in production.

### Auth Endpoints (All Levels)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|:-------------:|
| `POST` | `/api/v1/auth/register` | Register new user | No |
| `POST` | `/api/v1/auth/token` | Login, get JWT | No |
| `GET` | `/api/v1/auth/me` | Current user profile | Yes |
| `GET` | `/api/v1/auth/users/{id}` | Get user by ID | Yes |
| `PATCH` | `/api/v1/auth/users/{id}` | Update profile (self or admin) | Yes |
| `POST` | `/api/v1/auth/password-reset/request` | Request reset token | No |
| `POST` | `/api/v1/auth/password-reset/confirm` | Reset password with token | No |
| `POST` | `/api/v1/auth/verify-email` | Verify email address | No |
| `POST` | `/api/v1/auth/logout` | Invalidate current token | Yes |

---

## RBAC (Role-Based Access Control)

The RBAC level adds role enforcement on top of all Basic features.

### Role Constants

When RBAC is enabled, your project includes predefined role constants:

```python
# app/core/security.py
ROLE_ADMIN = "admin"
ROLE_MODERATOR = "moderator"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_MODERATOR, ROLE_USER}
```

The user model gains a `role` field:

```python
# app/models/user.py
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True)
    full_name: str | None = None
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)
    role: str = Field(default="user")  # Added by RBAC
```

### Protecting Endpoints with `require_role()`

The `require_role()` function is a FastAPI dependency that checks the authenticated user's role:

```python
from app.services.auth.auth_service import require_role
from fastapi import Depends

@router.get("/admin/dashboard")
async def admin_dashboard(user=Depends(require_role("admin"))):
    """Only accessible to admin users."""
    return {"message": f"Welcome, admin {user.email}"}

@router.get("/moderation")
async def moderation_panel(user=Depends(require_role("admin", "moderator"))):
    """Accessible to admins and moderators."""
    return {"queue": [...]}
```

If the user's role doesn't match, a `403 Forbidden` response is returned automatically.

### Role Permissions

| Action | Admin | Moderator | User |
|--------|:-----:|:---------:|:----:|
| List all users | :material-check: | :material-check: | |
| Update any user | :material-check: | | |
| Activate/deactivate users | :material-check: | | |
| Delete users | :material-check: | | |

- **Moderators** can list users but cannot modify them
- **Admins** have full user management capabilities

### Assigning Roles

Roles default to `"user"` on registration. To assign roles, update the user via the API:

```bash
# Update a user's role (admin endpoint)
curl -X PATCH http://localhost:8000/api/v1/auth/users/1 \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

### Auth Endpoints (RBAC+)

These endpoints are available at the RBAC and Org levels:

| Method | Endpoint | Description | Required Role |
|--------|----------|-------------|:-------------:|
| `GET` | `/api/v1/auth/users` | List all users | Admin / Moderator |
| `PATCH` | `/api/v1/auth/users/{id}/deactivate` | Deactivate user | Admin |
| `PATCH` | `/api/v1/auth/users/{id}/activate` | Activate user | Admin |
| `DELETE` | `/api/v1/auth/users/{id}` | Delete user | Admin |

---

## Organization Level

The Organization level adds multi-tenant support on top of all RBAC features.

### What You Get

- **Organization model**, name, slug (with validation), description, active status
- **Membership model**, links users to organizations with roles
- **Invite model**, email-based invitations with token acceptance
- **OrgService**, CRUD operations for organizations
- **MembershipService**, Add/remove members, update roles, list memberships, bulk operations
- **InviteService**, Create invites, accept invites, resolve pending invites on registration
- **REST API**, Full org, membership, and invite management endpoints
- **Dashboard**, Organizations tab + Org column in the Users tab

### Organization Models

```python
# app/models/org.py
class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    description: str | None = None
    is_active: bool = Field(default=True)
    created_at: datetime
    updated_at: datetime | None = None

class OrganizationMember(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id")
    user_id: int = Field(foreign_key="user.id")
    role: str = Field(default="member")  # owner, admin, or member
    joined_at: datetime
```

### Slug Validation

Organization slugs are validated to be **lowercase alphanumeric with hyphens only**. Invalid slugs are rejected at creation and update time.

```bash
# Valid slugs: acme-corp, my-org-123, team-alpha
# Invalid slugs: Acme Corp, my_org, my.org, --bad-slug
```

### Membership Management

```python
from app.services.auth.membership_service import MembershipService
from app.services.auth.org_service import OrgService

# Create an organization
org_service = OrgService(db)
org = await org_service.create_org(OrgCreate(
    name="Acme Corp",
    slug="acme-corp",
))

# Add members
membership_service = MembershipService(db)
await membership_service.add_member(org.id, user.id, role="owner")
await membership_service.add_member(org.id, other_user.id, role="member")

# List members
members = await membership_service.list_org_members(org.id)

# Update role
await membership_service.update_member_role(org.id, other_user.id, "admin")

# List user's organizations
orgs = await membership_service.list_user_orgs(user.id)
```

### Bulk Add Members

`POST /orgs/{id}/members/bulk` adds multiple members in a single request. The implementation avoids SQL `IN` clauses for scalability.

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/members/bulk \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [2, 3, 4, 5], "role": "member"}'
```

### Member Details

`GET /orgs/{id}/members/details` returns member records enriched with user emails and names. Org admins can access this endpoint without needing global admin privileges.

```bash
curl http://localhost:8000/api/v1/orgs/1/members/details \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN"
```

### Ownership Transfer

`POST /orgs/{id}/transfer-ownership` transfers the owner role to another member. Only the current owner can perform this action.

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/transfer-ownership \
  -H "Authorization: Bearer OWNER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_owner_id": 5}'
```

### Invite by Email

`POST /orgs/{id}/invites` sends an invitation to an email address:

- If the email belongs to an **existing user**, they are automatically added as a member
- If the email does **not** match an existing user, a **pending invite** is created and resolved when that user registers

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "newuser@example.com", "role": "member"}'
```

### Token-Based Invite Acceptance

`POST /auth/accept-invite` accepts an invite using a token. The behavior is controlled by the `INVITE_ACCEPTANCE_MODE` setting:

| Mode | Behavior |
|------|----------|
| `email` (default) | Token must be used by the user whose email matches the invite |
| `token` | Any authenticated user can accept the invite with a valid token |

```bash
curl -X POST http://localhost:8000/api/v1/auth/accept-invite \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token": "invite-token-here"}'
```

### Cascade Delete

Deleting resources cascades cleanly:

- **Deleting an organization** removes all its members and pending invites
- **Deleting a user** removes all their memberships and pending invites

### Org Role Hierarchy

| Role | View Org | Manage Members | Update Org | Delete Org | Transfer Ownership |
|------|:--------:|:--------------:|:----------:|:----------:|:------------------:|
| **Owner** | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: |
| **Admin** | :material-check: | :material-check: | :material-check: | | |
| **Member** | :material-check: | | | | |

- The **creator** of an organization is automatically assigned the `owner` role
- Owners cannot be removed from the organization
- Admins can add/remove members and update roles, but cannot delete the organization or transfer ownership

### Org Endpoints

| Method | Endpoint | Description | Required Role |
|--------|----------|-------------|:-------------:|
| `POST` | `/api/v1/orgs` | Create organization | Authenticated |
| `GET` | `/api/v1/orgs` | List user's organizations | Authenticated |
| `GET` | `/api/v1/orgs/all` | List all organizations | Admin |
| `GET` | `/api/v1/orgs/memberships` | All memberships | Admin |
| `GET` | `/api/v1/orgs/{id}` | Get organization details | Member+ |
| `PATCH` | `/api/v1/orgs/{id}` | Update organization | Admin / Owner |
| `DELETE` | `/api/v1/orgs/{id}` | Delete organization (cascades) | Owner |
| `POST` | `/api/v1/orgs/{id}/transfer-ownership` | Transfer ownership | Owner |
| `GET` | `/api/v1/orgs/{id}/members` | List members | Member+ |
| `GET` | `/api/v1/orgs/{id}/members/details` | Members with user info | Member+ |
| `POST` | `/api/v1/orgs/{id}/members` | Add member | Admin / Owner |
| `POST` | `/api/v1/orgs/{id}/members/bulk` | Bulk add members | Admin / Owner |
| `PATCH` | `/api/v1/orgs/{id}/members/{uid}` | Update member role | Admin / Owner |
| `DELETE` | `/api/v1/orgs/{id}/members/{uid}` | Remove member | Admin / Owner |
| `POST` | `/api/v1/orgs/{id}/invites` | Invite by email | Admin / Owner |
| `GET` | `/api/v1/orgs/{id}/invites` | List pending invites | Admin / Owner |
| `POST` | `/api/v1/auth/accept-invite` | Accept invite by token | Authenticated |

---

## Configuration Reference

All auth-related settings with their defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTH_ENABLED` | `true` | Enable/disable authentication. When `false`, dev mode is active |
| `DEV_USER_ROLE` | `"user"` | Role assigned to the dev user when auth is disabled |
| `SECRET_KEY` | *(required)* | Secret key for JWT signing. Must be set in production |
| `JWT_ALGORITHM` | `"HS256"` | Algorithm used for JWT encoding/decoding |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT token expiry in minutes |
| `PASSWORD_RESET_EXPIRE_MINUTES` | `60` | Password reset token expiry in minutes |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | `24` | Email verification token expiry in hours |
| `RATE_LIMIT_LOGIN_MAX` | `5` | Max login attempts per window |
| `RATE_LIMIT_LOGIN_WINDOW` | `60` | Login rate limit window in seconds |
| `RATE_LIMIT_REGISTER_MAX` | `3` | Max registration attempts per window |
| `RATE_LIMIT_REGISTER_WINDOW` | `60` | Registration rate limit window in seconds |
| `ACCOUNT_LOCKOUT_ATTEMPTS` | `5` | Failed login attempts before lockout |
| `ACCOUNT_LOCKOUT_MINUTES` | `15` | Lockout duration in minutes |
| `INVITE_ACCEPTANCE_MODE` | `"email"` | Invite acceptance mode: `email` or `token` (Org level only) |

---

## Audit Events Reference

All audit events emitted by the auth service. Events are structured JSON logs with the `event_type` field as the primary identifier.

| Event Type | When It Fires |
|------------|---------------|
| `auth.user_registered` | New user successfully registers |
| `auth.login_success` | User successfully authenticates |
| `auth.login_failed` | Login attempt with invalid credentials |
| `auth.account_locked` | Account locked after exceeding failed login threshold |
| `auth.logout` | User logs out (token revoked) |
| `auth.password_reset_requested` | Password reset token generated |
| `auth.password_reset_completed` | Password successfully reset via token |
| `auth.email_verified` | User verifies their email address |
| `auth.user_updated` | User profile updated |
| `auth.user_activated` | User account activated by admin |
| `auth.user_deactivated` | User account deactivated by admin |
| `auth.user_deleted` | User account deleted by admin |
| `auth.org_created` | Organization created (Org level) |
| `auth.org_updated` | Organization updated (Org level) |
| `auth.org_deleted` | Organization deleted (Org level) |
| `auth.member_added` | Member added to organization (Org level) |
| `auth.member_removed` | Member removed from organization (Org level) |
| `auth.member_role_updated` | Member role changed (Org level) |
| `auth.ownership_transferred` | Organization ownership transferred (Org level) |
| `auth.invite_created` | Invite sent to email (Org level) |
| `auth.invite_accepted` | Invite accepted by user (Org level) |

---

## Upgrading Between Levels

### Basic to RBAC

```bash
# Regenerate with RBAC level
aegis add-service auth[rbac]
```

**What changes:**

- `role` field added to the User model
- `require_role()` dependency available in `auth_service.py`
- Role constants (`ROLE_ADMIN`, `ROLE_MODERATOR`, `ROLE_USER`) added to `security.py`
- Admin-protected user management endpoints (list, activate, deactivate, delete)
- Moderator can list users

### RBAC to Organization

```bash
# Regenerate with org level
aegis add-service auth[org]
```

**What changes (in addition to RBAC):**

- Organization and OrganizationMember models added
- OrgService and MembershipService added
- InviteService for email-based invitations
- Organization REST API endpoints at `/api/v1/orgs`
- Invite acceptance endpoint at `/api/v1/auth/accept-invite`
- Organizations tab in the Overseer dashboard
- Org column in the Users tab showing membership
- Cascade delete behavior for orgs and users

---

## Next Steps

| Topic | Description |
|-------|-------------|
| **[API Reference](api.md)** | Complete endpoint documentation |
| **[Service Layer](integration.md)** | Service architecture and integration |
| **[CLI Commands](cli.md)** | User management CLI tools |
| **[Examples](examples.md)** | Real-world usage patterns |
