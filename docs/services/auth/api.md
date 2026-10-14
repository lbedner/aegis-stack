# API Reference

Complete reference for all authentication and organization API endpoints.

All endpoints are mounted under the versioned API prefix:

```
http://localhost:8000/api/v1/
```

Auth endpoints: `/api/v1/auth/*`
Org endpoints: `/api/v1/orgs/*`

---

## Auth Endpoints (All Levels)

### POST /auth/register

Register a new user account. Automatically accepts any pending org invites for the registered email. On success the response sets the same `<project>_session` + `<project>_refresh` cookie pair as `POST /auth/token` — the user lands signed-in without a second round-trip.

**Auth:** None
**Rate limited:** Yes

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `email` | `string` | Yes | Must be unique |
| `password` | `string` | Yes | Minimum 8 characters |
| `full_name` | `string` | No | Display name |
| `is_active` | `boolean` | No | Defaults to `true` |

**Response: `200 OK`**

| Field | Type |
|-------|------|
| `id` | `integer` |
| `email` | `string` |
| `full_name` | `string \| null` |
| `is_active` | `boolean` |
| `is_verified` | `boolean` |
| `role` | `string` |
| `last_login` | `datetime \| null` |
| `created_at` | `datetime` |
| `updated_at` | `datetime \| null` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | User created |
| `400` | Email already registered |
| `422` | Validation error (invalid email, short password) |
| `429` | Rate limit exceeded |

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secure123", "full_name": "Jane Doe"}'
```

---

### POST /auth/token

Login and receive a JWT access token. Follows the OAuth2 password flow; email is passed as `username` in form data.

On success the response also sets two cookies:

Both are named for the project (`PROJECT_NAME`, e.g. `my-app_session`): browsers share a host's cookies across its ports, so two apps on `localhost` never overwrite each other's sign-in.

- `<project>_session` — HttpOnly access token, `Path=/`, `SameSite=Lax`. Browser flows ride on this.
- `<project>_refresh` — HttpOnly opaque refresh token, `Path=/api/v1/auth`, `SameSite=Strict`. Sent only on auth endpoints; used to rotate `<project>_session` once the access token expires.

API clients (CLIs, server-to-server) keep using the body's `access_token` as a bearer header; cookies are a parallel surface, not exclusive.

**Auth:** None
**Rate limited:** Yes

**Request body:** `application/x-www-form-urlencoded`

| Field | Type | Required |
|-------|------|----------|
| `username` | `string` | Yes, pass email here |
| `password` | `string` | Yes |

**Response: `200 OK`**

| Field | Type |
|-------|------|
| `access_token` | `string` |
| `token_type` | `string`, always `"bearer"` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Login successful |
| `401` | Incorrect email or password |
| `403` | Account temporarily locked |
| `429` | Rate limit exceeded |

!!! info "Account Lockout"
    Repeated failed login attempts temporarily lock the account. The lock lifts automatically after a cooldown period.

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=secure123"
```

---

### GET /auth/me

Get the current authenticated user's profile.

**Auth:** Bearer token required

**Response: `200 OK`**, `UserResponse` (see schema above)

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Missing or invalid token |

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /auth/users/{user_id}

Get a specific user by ID.

**Auth:** Bearer token required (any authenticated user)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `integer` | User ID |

**Response: `200 OK`**, `UserResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `404` | User not found |

```bash
curl http://localhost:8000/api/v1/auth/users/42 \
  -H "Authorization: Bearer $TOKEN"
```

---

### PATCH /auth/users/{user_id}

Update a user's profile. Caller must be the user themselves or an admin.

**Auth:** Bearer token required

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `integer` | User ID |

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `full_name` | `string` | No | New display name |

**Response: `200 OK`**, `UserResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `400` | No fields provided |
| `401` | Not authenticated |
| `403` | Not the user or an admin |
| `404` | User not found |

```bash
curl -X PATCH "http://localhost:8000/api/v1/auth/users/42?full_name=Jane+Smith" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /auth/password-reset/request

Request a password reset token. Always returns `200` regardless of whether the email exists, to avoid leaking account existence.

**Auth:** None
**Rate limited:** Yes

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `email` | `string` | Yes |

**Response: `200 OK`**

```json
{"detail": "If an account exists, a reset token has been created"}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Always (email may or may not exist) |
| `429` | Rate limit exceeded |

```bash
curl -X POST http://localhost:8000/api/v1/auth/password-reset/request \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'
```

---

### POST /auth/password-reset/confirm

Reset a password using a valid reset token.

**Auth:** None

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `token` | `string` | Yes | Token from reset request |
| `new_password` | `string` | Yes | Minimum 8 characters |

**Response: `200 OK`**

```json
{"detail": "Password has been reset successfully"}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Password reset |
| `400` | Invalid or expired token |

```bash
curl -X POST http://localhost:8000/api/v1/auth/password-reset/confirm \
  -H "Content-Type: application/json" \
  -d '{"token": "abc123", "new_password": "newpassword1"}'
```

---

### POST /auth/verify-email

Verify a user's email address using the verification token sent at registration.

**Auth:** None

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `token` | `string` | Yes |

**Response: `200 OK`**

```json
{"detail": "Email has been verified successfully"}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Email verified |
| `400` | Invalid or expired token |

```bash
curl -X POST http://localhost:8000/api/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token": "abc123"}'
```

---

### POST /auth/refresh

Rotate the refresh token and mint a fresh access token. Reads the `<project>_refresh` cookie, revokes the inbound row, inserts a successor in the same family, and sets both cookies fresh. Returns the new access token in the body so bearer clients can update their header.

**Auth:** `<project>_refresh` cookie required (no bearer fallback — refresh tokens never travel in `Authorization` headers).

**Response: `200 OK`**

| Field | Type |
|-------|------|
| `access_token` | `string` |
| `token_type` | `string`, always `"bearer"` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Rotation succeeded; new tokens in cookies + body |
| `401` | Missing, expired, or revoked refresh cookie |

!!! warning "Reuse detection"
    Replaying a refresh token that has already been rotated triggers **family-wide revocation**: every refresh token descending from the same original sign-in is marked revoked, forcing re-auth on the next request. This is the standard OAuth2 defense against stolen-token replay.

The browser-side `APIClient` in the generated frontend calls this endpoint transparently on any other-endpoint `401` and retries the original request once. Most users will never see a refresh response directly.

```bash
# Cookie-bearing clients (browsers, curl with -b)
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -b "<project>_refresh=$REFRESH_TOKEN"
```

---

### POST /auth/logout

Sign the user out. Revokes the refresh token in the database and drops both cookies. The short-lived access JWT is left to expire naturally (~15 minutes) — there is no stateful blacklist.

**Auth:** Bearer token or `<project>_session` cookie required.

**Response: `200 OK`**

```json
{"detail": "Logged out"}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Logged out; refresh row revoked, both cookies cleared |
| `401` | Not authenticated (both cookies are still cleared so the client lands in a clean state) |

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /auth/accept-invite

Accept an org invite by token. The invite must have been issued to the authenticated user's email.

**Auth:** Bearer token required

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `token` | `string` | Yes, invite token |

**Response: `200 OK`**, `InviteResponse`

| Field | Type |
|-------|------|
| `id` | `integer` |
| `organization_id` | `integer` |
| `email` | `string` |
| `role` | `string` |
| `status` | `string` |
| `token` | `string` |
| `created_at` | `datetime` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Invite accepted |
| `400` | Invalid token, already accepted, or email mismatch |
| `401` | Not authenticated |

```bash
curl -X POST http://localhost:8000/api/v1/auth/accept-invite \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token": "invite-token-here"}'
```

---

## Auth Endpoints (RBAC+)

These endpoints require elevated roles (`admin` or `moderator`).

### GET /auth/users

List all users. Requires `admin` or `moderator` role.

**Auth:** Bearer token, `admin` or `moderator`

**Response: `200 OK`**, `list[UserResponse]`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Insufficient role |

```bash
curl http://localhost:8000/api/v1/auth/users \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### PATCH /auth/users/{user_id}/deactivate

Deactivate a user account. Requires `admin` role.

**Auth:** Bearer token, `admin`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `integer` | User to deactivate |

**Response: `200 OK`**, `UserResponse` with `is_active: false`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | User deactivated |
| `401` | Not authenticated |
| `403` | Not admin |
| `404` | User not found |

```bash
curl -X PATCH http://localhost:8000/api/v1/auth/users/42/deactivate \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### PATCH /auth/users/{user_id}/activate

Reactivate a deactivated user account. Requires `admin` role.

**Auth:** Bearer token, `admin`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `integer` | User to activate |

**Response: `200 OK`**, `UserResponse` with `is_active: true`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | User activated |
| `401` | Not authenticated |
| `403` | Not admin |
| `404` | User not found |

```bash
curl -X PATCH http://localhost:8000/api/v1/auth/users/42/activate \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### DELETE /auth/users/{user_id}

Permanently delete a user. Requires `admin` role.

**Auth:** Bearer token, `admin`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `integer` | User to delete |

**Response: `204 No Content`**

**Status codes:**

| Code | Condition |
|------|-----------|
| `204` | User deleted |
| `401` | Not authenticated |
| `403` | Not admin |
| `404` | User not found |

```bash
curl -X DELETE http://localhost:8000/api/v1/auth/users/42 \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Org Endpoints

All org endpoints require authentication. Role requirements vary per endpoint.

**Org roles:** `owner` > `admin` > `member`

### POST /orgs

Create a new organization. The creator is automatically added as `owner`.

**Auth:** Bearer token required

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | `string` | Yes | Display name |
| `slug` | `string` | Yes | Unique URL identifier, lowercase alphanumeric with hyphens, cannot start/end with a hyphen |
| `description` | `string` | No | |
| `is_active` | `boolean` | No | Defaults to `true` |

**Response: `201 Created`**, `OrgResponse`

| Field | Type |
|-------|------|
| `id` | `integer` |
| `name` | `string` |
| `slug` | `string` |
| `description` | `string \| null` |
| `is_active` | `boolean` |
| `created_at` | `datetime` |
| `updated_at` | `datetime \| null` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `201` | Organization created |
| `400` | Invalid slug format or slug already taken |
| `401` | Not authenticated |

```bash
curl -X POST http://localhost:8000/api/v1/orgs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme-corp", "description": "Our org"}'
```

---

### GET /orgs

List organizations the current user belongs to.

**Auth:** Bearer token required

**Response: `200 OK`**, `list[OrgResponse]`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |

```bash
curl http://localhost:8000/api/v1/orgs \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /orgs/all

List all organizations in the system. Requires `admin` role.

**Auth:** Bearer token, `admin`

**Response: `200 OK`**, `list[OrgResponse]`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Not admin |

```bash
curl http://localhost:8000/api/v1/orgs/all \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### GET /orgs/memberships

List all memberships across all orgs with org name and slug. Requires `admin` role.

**Auth:** Bearer token, `admin`

**Response: `200 OK`**, `list[UserMembershipResponse]`

| Field | Type |
|-------|------|
| `user_id` | `integer` |
| `org_name` | `string` |
| `org_slug` | `string` |
| `role` | `string` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Not admin |

```bash
curl http://localhost:8000/api/v1/orgs/memberships \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### GET /orgs/{org_id}

Get organization details. Requires membership in the org.

**Auth:** Bearer token, any org member

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Response: `200 OK`**, `OrgResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Not a member |
| `404` | Organization not found |

```bash
curl http://localhost:8000/api/v1/orgs/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

### PATCH /orgs/{org_id}

Update organization name or description. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `string` | No | New display name |
| `description` | `string` | No | New description |

**Response: `200 OK`**, `OrgResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `400` | No fields provided |
| `401` | Not authenticated |
| `403` | Insufficient org role |
| `404` | Organization not found |

```bash
curl -X PATCH "http://localhost:8000/api/v1/orgs/1?name=Acme+Inc" \
  -H "Authorization: Bearer $TOKEN"
```

---

### DELETE /orgs/{org_id}

Delete an organization. Requires `owner` org role.

**Auth:** Bearer token, org `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Response: `204 No Content`**

**Status codes:**

| Code | Condition |
|------|-----------|
| `204` | Organization deleted |
| `401` | Not authenticated |
| `403` | Not the owner |
| `404` | Organization not found |

```bash
curl -X DELETE http://localhost:8000/api/v1/orgs/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /orgs/{org_id}/transfer-ownership

Transfer org ownership to another existing member. Caller must be the current `owner`.

**Auth:** Bearer token, org `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | `integer` | Yes | Must already be a member |

**Response: `200 OK`**

```json
{"detail": "Ownership transferred"}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Ownership transferred |
| `400` | Target user is not a member |
| `401` | Not authenticated |
| `403` | Not the owner |

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/transfer-ownership \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": 99}'
```

---

### GET /orgs/{org_id}/members

List organization members. Requires membership.

**Auth:** Bearer token, any org member

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Response: `200 OK`**, `list[MemberResponse]`

| Field | Type |
|-------|------|
| `id` | `integer` |
| `organization_id` | `integer` |
| `user_id` | `integer` |
| `role` | `string` |
| `joined_at` | `datetime` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Not a member |

```bash
curl http://localhost:8000/api/v1/orgs/1/members \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /orgs/{org_id}/members/details

List members with enriched user data (email and name). Requires membership.

**Auth:** Bearer token, any org member

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Response: `200 OK`**, `list[MemberDetailResponse]`

| Field | Type |
|-------|------|
| `user_id` | `integer` |
| `email` | `string` |
| `full_name` | `string \| null` |
| `role` | `string` |
| `joined_at` | `datetime` |

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Not a member |

```bash
curl http://localhost:8000/api/v1/orgs/1/members/details \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /orgs/{org_id}/members

Add a single member to the organization. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Query parameters:**

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `user_id` | `integer` | Yes | User to add |
| `role` | `string` | No | Defaults to `"member"`, valid: `owner`, `admin`, `member` |

**Response: `201 Created`**, `MemberResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `201` | Member added |
| `400` | User is already a member |
| `401` | Not authenticated |
| `403` | Insufficient org role |

```bash
curl -X POST "http://localhost:8000/api/v1/orgs/1/members?user_id=42&role=admin" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /orgs/{org_id}/members/bulk

Add multiple members at once, all with the same role. Requires `admin` or `owner` org role. Skips users already in the org.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_ids` | `list[integer]` | Yes | User IDs to add |
| `role` | `string` | No | Defaults to `"member"`, valid: `owner`, `admin`, `member` |

**Response: `201 Created`**, `list[MemberResponse]` (newly added members only)

**Status codes:**

| Code | Condition |
|------|-----------|
| `201` | Members added |
| `400` | Invalid role |
| `401` | Not authenticated |
| `403` | Insufficient org role |

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/members/bulk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [42, 43, 44], "role": "member"}'
```

---

### PATCH /orgs/{org_id}/members/{user_id}

Update a member's role. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |
| `user_id` | `integer` | Member's user ID |

**Query parameters:**

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `role` | `string` | Yes | Valid: `owner`, `admin`, `member` |

**Response: `200 OK`**, `MemberResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Role updated |
| `400` | Invalid role |
| `401` | Not authenticated |
| `403` | Insufficient org role |
| `404` | Member not found |

```bash
curl -X PATCH "http://localhost:8000/api/v1/orgs/1/members/42?role=admin" \
  -H "Authorization: Bearer $TOKEN"
```

---

### DELETE /orgs/{org_id}/members/{user_id}

Remove a member from the organization. The `owner` cannot be removed, transfer ownership first. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |
| `user_id` | `integer` | Member's user ID |

**Response: `204 No Content`**

**Status codes:**

| Code | Condition |
|------|-----------|
| `204` | Member removed |
| `401` | Not authenticated |
| `403` | Insufficient org role, or attempting to remove owner |
| `404` | Member not found |

```bash
curl -X DELETE http://localhost:8000/api/v1/orgs/1/members/42 \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /orgs/{org_id}/invites

Invite a user to the org by email. If the user already has an account, they are added immediately and the invite is marked as accepted. For pending invites (user doesn't exist yet), they auto-join on registration or can accept explicitly via `POST /auth/accept-invite`. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Request body:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `email` | `string` | Yes | Invitee's email |
| `role` | `string` | No | Defaults to `"member"`, valid: `owner`, `admin`, `member` |

**Response: `201 Created`**, `InviteResponse`

**Status codes:**

| Code | Condition |
|------|-----------|
| `201` | Invite created |
| `400` | User already a member or invite already pending |
| `401` | Not authenticated |
| `403` | Insufficient org role |

```bash
curl -X POST http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "newuser@example.com", "role": "member"}'
```

---

### GET /orgs/{org_id}/invites

List pending invites for an organization. Requires `admin` or `owner` org role.

**Auth:** Bearer token, org `admin` or `owner`

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | `integer` | Organization ID |

**Response: `200 OK`**, `list[InviteResponse]`

**Status codes:**

| Code | Condition |
|------|-----------|
| `200` | Success |
| `401` | Not authenticated |
| `403` | Insufficient org role |

```bash
curl http://localhost:8000/api/v1/orgs/1/invites \
  -H "Authorization: Bearer $TOKEN"
```

---

## Common Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Resource created |
| `204` | Success, no content |
| `400` | Bad request, validation or business rule failure |
| `401` | Not authenticated |
| `403` | Authenticated but lacks required role or org permission |
| `404` | Resource not found |
| `422` | Request body schema validation error |
| `429` | Rate limit exceeded |

---

**See also:**

- **[Integration Guide](integration.md)**, How to integrate auth into your app
- **[CLI Commands](cli.md)**, Manage users and orgs from the command line
- **[Examples](examples.md)**, Complete implementation examples
