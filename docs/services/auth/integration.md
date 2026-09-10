# Auth Service Integration

Reference for integrating auth services into your own endpoints and background tasks. All services are async, database-backed, and injected via FastAPI's dependency system.

## Service Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Endpoint                      │
│   Depends(get_user_service)  Depends(get_org_service)   │
└──────────┬───────────────────────────┬──────────────────┘
           │                           │
           ▼                           ▼
    ┌─────────────┐           ┌─────────────────┐
    │ UserService │           │   OrgService    │
    │             │           │                 │
    │  create     │           │  create         │
    │  get        │           │  get / update   │
    │  update     │           │  delete / list  │
    │  delete     │           └────────┬────────┘
    │  lockout    │                    │
    │  pw reset   │                    ▼
    │  email ver  │       ┌──────────────────────┐
    └─────────────┘       │  MembershipService   │
           │              │                      │
           │              │  add / remove member │
           │              │  update role         │
           │              │  transfer ownership  │
           │              │  bulk add            │
           │              │  list with details   │
           └──────────────┴──────────┬───────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │   InviteService     │
                          │                     │
                          │  create invite      │
                          │  accept by token    │
                          │  accept pending     │
                          │  list pending       │
                          └─────────────────────┘

DB-backed session services:
  ┌─────────────────┐
  │  RefreshService │  mint / rotate / revoke / family revocation
  └─────────────────┘

Infrastructure (singletons, no DB dependency):
  ┌─────────────────┐  ┌─────────────────┐
  │  AuditEmitter   │  │   RateLimiter   │
  └─────────────────┘  └─────────────────┘
```

`UserService`, `OrgService`, `MembershipService`, and `InviteService` each accept an `AsyncSession` in their constructor. Use the dependency functions in `deps.py` to get properly scoped instances. Never instantiate services directly in endpoints.

---

## UserService

Manages user lifecycle: creation, lookup, updates, deactivation, password reset, email verification, and account lockout.

```python
class UserService:
    def __init__(self, db: AsyncSession) -> None
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `create_user` | `(user_data: UserCreate) -> User` | Hash password and persist new user. Email is lowercased. |
| `get_user_by_email` | `(email: str) -> User \| None` | Case-insensitive email lookup. |
| `get_user_by_id` | `(user_id: int) -> User \| None` | Fetch by primary key. |
| `update_user` | `(user_id: int, **updates) -> User \| None` | Set arbitrary model fields. Sets `updated_at`. |
| `activate_user` | `(user_id: int) -> User \| None` | Set `is_active=True`. |
| `deactivate_user` | `(user_id: int) -> User \| None` | Set `is_active=False`. |
| `delete_user` | `(user_id: int) -> bool` | Permanent delete. Cleans up memberships and invites first. |
| `list_users` | `() -> list[User]` | All users, newest first. |
| `find_existing_emails_with_prefix` | `(prefix: str, domain: str) -> list[str]` | Find emails matching `prefix*@domain`. Used by CLI to auto-increment test users. |
| `create_password_reset_token` | `(email: str) -> str \| None` | Create a `PasswordResetToken` record, return the token string. Returns `None` if user not found, callers should not reveal this. |
| `reset_password` | `(token: str, new_password: str) -> None` | Validate token, set new hashed password, mark token used. Raises `ValueError` on invalid/expired token. |
| `create_email_verification_token` | `(user_id: int) -> str` | Create an `EmailVerificationToken` record, return the token string. |
| `verify_email` | `(token: str) -> None` | Set `user.is_verified=True`, mark token used. Raises `ValueError` on invalid/expired token. |
| `record_failed_login` | `(email: str) -> None` | Increment `failed_login_attempts`. Locks account when threshold (`ACCOUNT_LOCKOUT_ATTEMPTS`) is reached. |
| `reset_login_attempts` | `(user_id: int) -> None` | Zero out failed attempts and clear `locked_until`. |
| `is_account_locked` | `(user: User) -> bool` | Check lockout. Auto-unlocks and persists to DB when `locked_until` has passed. |

### Example: Registration with email verification

```python
from app.components.backend.api.deps import get_user_service
from app.services.auth.user_service import UserService
from app.models.user import UserCreate

@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    user_service: UserService = Depends(get_user_service),
):
    existing = await user_service.get_user_by_email(user_data.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await user_service.create_user(user_data)
    token = await user_service.create_email_verification_token(user.id)

    # Send token via your email provider
    await send_verification_email(user.email, token)
    return UserResponse.model_validate(user)
```

### Example: Login with lockout and failed-attempt tracking

```python
@router.post("/token")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_service: UserService = Depends(get_user_service),
):
    user = await user_service.get_user_by_email(form_data.username)

    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if await user_service.is_account_locked(user):
        raise HTTPException(
            status_code=403,
            detail="Account locked due to too many failed login attempts. Please try again later.",
        )

    if not verify_password(form_data.password, user.hashed_password):
        await user_service.record_failed_login(user.email)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    await user_service.reset_login_attempts(user.id)
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}
```

---

## OrgService

CRUD operations for organizations. Organizations are identified by both integer ID and a unique string slug.

```python
class OrgService:
    def __init__(self, db: AsyncSession) -> None
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `create_org` | `(org_data: OrgCreate) -> Organization` | Persist a new organization. |
| `get_org_by_id` | `(org_id: int) -> Organization \| None` | Fetch by primary key. |
| `get_org_by_slug` | `(slug: str) -> Organization \| None` | Fetch by unique slug. |
| `update_org` | `(org_id: int, **updates: str) -> Organization \| None` | Update arbitrary fields. Sets `updated_at`. |
| `delete_org` | `(org_id: int) -> bool` | Delete org and all its memberships. |
| `list_orgs` | `() -> list[Organization]` | All organizations, newest first. |

### Example

```python
from app.components.backend.api.deps import get_org_service
from app.services.auth.org_service import OrgService
from app.models.org import OrgCreate, OrgResponse

@router.post("/orgs", response_model=OrgResponse)
async def create_org(
    org_data: OrgCreate,
    org_service: OrgService = Depends(get_org_service),
):
    existing = await org_service.get_org_by_slug(org_data.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Slug already in use")
    org = await org_service.create_org(org_data)
    return OrgResponse.model_validate(org)
```

---

## MembershipService

Manages the relationship between users and organizations. Valid roles are `owner`, `admin`, and `member` (defined in `VALID_ORG_ROLES`).

```python
class MembershipService:
    def __init__(self, db: AsyncSession) -> None
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `add_member` | `(org_id: int, user_id: int, role: str = "member") -> OrganizationMember` | Add a user to an org. Raises `ValueError` for invalid roles. |
| `remove_member` | `(org_id: int, user_id: int) -> bool` | Remove a membership record. Returns `False` if not found. |
| `get_member` | `(org_id: int, user_id: int) -> OrganizationMember \| None` | Fetch a specific membership. |
| `update_member_role` | `(org_id: int, user_id: int, role: str) -> OrganizationMember \| None` | Change a member's role. Raises `ValueError` for invalid roles. |
| `transfer_ownership` | `(org_id: int, current_owner_id: int, new_owner_id: int) -> None` | Atomically demote current owner to `admin` and promote new owner. New owner must already be a member. |
| `bulk_add_members` | `(org_id: int, user_ids: list[int], role: str = "member") -> list[OrganizationMember]` | Batch-add users. Skips existing members. Single query to fetch existing IDs, then bulk insert. Returns only newly added records. |
| `list_org_members` | `(org_id: int) -> list[OrganizationMember]` | All membership records for an org. |
| `list_org_members_with_details` | `(org_id: int) -> list[dict]` | Members with user email and full name. Single JOIN query. |
| `list_user_orgs` | `(user_id: int) -> list[Organization]` | All organizations a user belongs to. |
| `list_all_memberships` | `() -> list[dict]` | All memberships with org name and slug. Single JOIN query. |

### Example: Bulk-add members after org creation

```python
from app.components.backend.api.deps import get_membership_service
from app.services.auth.membership_service import MembershipService

@router.post("/orgs/{org_id}/members/bulk")
async def bulk_add(
    org_id: int,
    body: BulkAddMembersRequest,
    current_user: User = Depends(require_role("admin", "owner")),
    membership_service: MembershipService = Depends(get_membership_service),
):
    added = await membership_service.bulk_add_members(org_id, body.user_ids, body.role)
    return {"added": len(added)}
```

### Example: Transfer ownership

```python
@router.post("/orgs/{org_id}/transfer-ownership")
async def transfer_ownership(
    org_id: int,
    body: TransferOwnershipRequest,
    current_user: User = Depends(require_role("owner")),
    membership_service: MembershipService = Depends(get_membership_service),
):
    await membership_service.transfer_ownership(org_id, current_user.id, body.user_id)
    return {"status": "ownership transferred"}
```

### Example: List members with user details

```python
@router.get("/orgs/{org_id}/members/details", response_model=list[MemberDetailResponse])
async def list_member_details(
    org_id: int,
    user=Depends(_get_current_user),
    membership_service: MembershipService = Depends(get_membership_service),
):
    return await membership_service.list_org_members_with_details(org_id)
```

---

## InviteService

Handles org invitations. Invites can be sent to users who don't yet have an account, pending invites are automatically accepted when the user registers.

```python
class InviteService:
    def __init__(self, db: AsyncSession) -> None
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `create_invite` | `(org_id: int, email: str, role: str, invited_by: int) -> OrgInvite` | Create invite. If user already exists, adds them immediately and marks invite `accepted`. Raises `ValueError` on duplicate pending invite or existing membership. |
| `accept_invite_by_token` | `(token: str, caller_email: str, caller_user_id: int) -> OrgInvite` | Accept a pending invite. In `email` mode (`INVITE_ACCEPTANCE_MODE`), `caller_email` must match the invite. Adds user to the org and marks invite `accepted`. |
| `accept_pending_invites` | `(email: str, user_id: int) -> int` | Accept all pending invites for an email address. Call this after user registration. Returns the count of invites accepted. |
| `list_pending_invites` | `(org_id: int) -> list[OrgInvite]` | All pending invites for an org. |

### Invite status flow

```
create_invite()
    ├─ user exists  →  add to org immediately  →  status: "accepted"
    └─ user absent  →  store pending invite    →  status: "pending"
                                                        │
                            ┌───────────────────────────┘
                            ▼
        accept_pending_invites()  ─ called at registration
        accept_invite_by_token()  ─ called from invite link
                            │
                            └─  MembershipService.add_member()
                                invite.status = "accepted"
```

### Example: Send invite

```python
from app.components.backend.api.deps import get_invite_service
from app.services.auth.invite_service import InviteService

@router.post("/orgs/{org_id}/invites", response_model=InviteResponse)
async def invite_member(
    org_id: int,
    body: InviteCreate,
    current_user: User = Depends(require_role("admin", "owner")),
    invite_service: InviteService = Depends(get_invite_service),
):
    invite = await invite_service.create_invite(
        org_id=org_id,
        email=body.email,
        role=body.role,
        invited_by=current_user.id,
    )
    if invite.status == "pending":
        await send_invite_email(body.email, invite.token)
    return InviteResponse.model_validate(invite)
```

### Example: Accept pending invites on registration

```python
@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    user_service: UserService = Depends(get_user_service),
    invite_service: InviteService = Depends(get_invite_service),
):
    user = await user_service.create_user(user_data)

    # Fulfill any pending invites for this email
    await invite_service.accept_pending_invites(user.email, user.id)

    return UserResponse.model_validate(user)
```

### Example: Accept invite by token

```python
@router.post("/auth/accept-invite", response_model=InviteResponse)
async def accept_invite(
    body: AcceptInviteRequest,
    current_user: User = Depends(get_current_user),
    invite_service: InviteService = Depends(get_invite_service),
):
    invite = await invite_service.accept_invite_by_token(
        token=body.token,
        caller_email=current_user.email,
        caller_user_id=current_user.id,
    )
    return InviteResponse.model_validate(invite)
```

---

## Dependency Injection

All services are wired in `app/components/backend/api/deps.py`. Each dependency function creates a fresh service instance bound to a scoped `AsyncSession`.

### Available dependencies

```python
# app/components/backend/api/deps.py

async def get_async_db() -> AsyncGenerator[AsyncSession]:
    """Scoped async session. Auto-commits on success, rolls back on exception."""

async def get_user_service(db: AsyncSession = Depends(get_async_db)) -> UserService:
    """UserService bound to a request-scoped session."""

async def get_org_service(db: AsyncSession = Depends(get_async_db)) -> OrgService:
    """OrgService bound to a request-scoped session."""

async def get_membership_service(db: AsyncSession = Depends(get_async_db)) -> MembershipService:
    """MembershipService bound to a request-scoped session."""

async def get_invite_service(db: AsyncSession = Depends(get_async_db)) -> InviteService:
    """InviteService bound to a request-scoped session."""

def get_audit() -> AuditEmitter:
    """Return the global audit_emitter singleton."""
```

### Using multiple services in one endpoint

When an endpoint needs multiple services, each `Depends(get_*_service)` call chains through `Depends(get_async_db)`. FastAPI deduplicates dependencies within a request, so all services in a single request share the same session.

```python
from app.components.backend.api.deps import (
    get_org_service,
    get_membership_service,
    get_audit,
)

@router.post("/orgs", response_model=OrgResponse)
async def create_org_with_owner(
    org_data: OrgCreate,
    current_user: User = Depends(get_current_user),
    org_service: OrgService = Depends(get_org_service),
    membership_service: MembershipService = Depends(get_membership_service),
    audit: AuditEmitter = Depends(get_audit),
):
    org = await org_service.create_org(org_data)
    await membership_service.add_member(org.id, current_user.id, role="owner")
    await audit.emit(
        "org.created",
        actor_id=current_user.id,
        actor_email=current_user.email,
        target_type="org",
        target_id=org.id,
    )
    return OrgResponse.model_validate(org)
```

### Role-based access control

`require_role()` is a dependency factory from `app.services.auth.auth_service`. It validates the JWT, loads the user, and checks their system-level role.

```python
from app.services.auth.auth_service import require_role

# Single role
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    user_service: UserService = Depends(get_user_service),
):
    deleted = await user_service.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

# Multiple system roles accepted
@router.get("/auth/users")
async def list_users(
    current_user: User = Depends(require_role("admin", "moderator")),
    user_service: UserService = Depends(get_user_service),
):
    return await user_service.list_users()
```

!!! info "Development mode"
    When `AUTH_ENABLED=false`, `require_role()` bypasses token validation and returns a synthetic dev user with the role configured in `DEV_USER_ROLE`. This applies to all auth dependencies uniformly.

---

## Infrastructure

### RefreshService

DB-backed refresh-token store with rotation and reuse detection. The access JWT stays short-lived (15 min by default) and stateless; long-lived sessions are carried by an opaque refresh-token row that gets rotated on every use.

```python
# app/services/auth/refresh_service.py
from app.services.auth.deps import get_refresh_service
from app.services.auth.refresh_service import RefreshService

# Injected like any other service
async def my_handler(
    refresh_service: RefreshService = Depends(get_refresh_service),
):
    ...
```

The data model is one table:

```python
class RefreshToken(SQLModel, table=True):
    token: str       # opaque 32-byte url-safe random, PK
    user_id: int     # FK → user.id (cascade on delete)
    family_id: str   # uuid, groups rotated successors
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
```

**`RefreshService` surface:**

| Method | Signature | Behavior |
|--------|-----------|----------|
| `mint` | `(user_id, family_id=None) -> token` | Insert a new refresh row. Callers minting a fresh sign-in leave `family_id=None`. |
| `rotate` | `(token) -> (new_token, user_id) \| None` | Revoke inbound, insert successor in the same family. Returns `None` on miss / expired / replay. |
| `revoke` | `(token) -> None` | Mark a single row revoked. Idempotent — logout with a stale cookie never 500s. |
| `revoke_family` | `(family_id) -> None` | Revoke every live row in the family. Used on reuse detection and as the basis for a future "sign out everywhere" feature. |
| `validate` | `(token) -> user_id \| None` | Read-only check. Used by diagnostic paths; the hot refresh path uses `rotate`. |

**Rotation contract:**

```python
# Endpoint shape — see app/components/backend/api/auth/router.py
@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    refresh_service: RefreshService = Depends(get_refresh_service),
):
    inbound = request.cookies.get("aegis_refresh")
    result = await refresh_service.rotate(inbound)
    if result is None:
        # Stale, expired, or replay — drop both cookies and 401.
        clear_session_cookie(response)
        clear_refresh_cookie(response)
        raise HTTPException(401)
    new_refresh, user_id = result
    # Mint a new access JWT, set both cookies fresh.
    ...
```

**Reuse detection.** Replaying an already-rotated refresh token (e.g. a stolen cookie that the attacker has already used once before the victim noticed) triggers a family-wide revocation. Every refresh row descending from the same sign-in is marked revoked, forcing re-auth across the chain.

```python
# Inside rotate(), if row.revoked_at is not None:
await self.revoke_family(row.family_id)
return None
```

!!! info "Why opaque tokens, not JWT refresh"
    Refresh tokens are 32-byte random strings — *not* JWTs. The DB row is the source of truth so revocation is O(1) and atomic. JWT refresh tokens are weak by default because revoking individual ones requires a blacklist anyway, which defeats the purpose.

!!! info "Why DB, not Redis"
    Auth already requires the DB, refresh rows are bounded (one active per device per session), and PK lookup is microseconds. A `RefreshTokenStore` protocol leaves room to plug Redis in later without redesigning anything.

---

### AuditEmitter

Structured audit logging with a pluggable backend. The default backend writes to the `audit` logger as structured JSON. All fields except `event_type` are optional.

```python
# app/core/audit.py
audit_emitter = AuditEmitter()  # global singleton
```

```python
# Inject via Depends(get_audit) in endpoints
from app.components.backend.api.deps import get_audit
from app.core.audit import AuditEmitter

@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    user_service: UserService = Depends(get_user_service),
    audit: AuditEmitter = Depends(get_audit),
):
    user = await user_service.deactivate_user(user_id)
    await audit.emit(
        "user.deactivated",
        actor_id=current_user.id,
        actor_email=current_user.email,
        target_type="user",
        target_id=user_id,
        detail=f"Deactivated by {current_user.email}",
    )
    return UserResponse.model_validate(user)
```

**Standard event type naming:** `<domain>.<action>`, for example `auth.login_success`, `org.member_added`, `user.password_reset`.

---

### RateLimiter

Sliding-window, in-memory rate limiter. Three pre-configured instances cover the main auth endpoints:

```python
# app/components/backend/security/rate_limit.py
login_limiter          = RateLimiter(max_requests=5,  window_seconds=60)
register_limiter       = RateLimiter(max_requests=3,  window_seconds=60)
password_reset_limiter = RateLimiter(max_requests=3,  window_seconds=60)
```

The module also exposes thin `Depends`-able wrappers (`login_rate_limit`,
`register_rate_limit`, `password_reset_rate_limit`) re-exported from
`app/components/backend/api/deps.py`. Add the matching dep to your
route signature; it raises `HTTP 429` with a `Retry-After` header when
the limit is exceeded.

```python
from app.components.backend.api.deps import login_rate_limit

@router.post("/token")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_service: UserService = Depends(get_user_service),
    _rate_limit: None = Depends(login_rate_limit),
):
    # ... authentication logic
```

Set `TRUST_PROXY_HEADERS=true` in settings when running behind a reverse proxy so the limiter reads the real client IP from `X-Forwarded-For` rather than the proxy's address.

!!! warning "Process-local storage"
    Rate limit counters are in-memory and not shared across processes. For multi-worker deployments, use a Redis-backed rate limiter.

---

**Related:**

- **[API Reference](api.md)** - Endpoint documentation
- **[CLI Commands](cli.md)** - User and org management from the command line
- **[Examples](examples.md)** - End-to-end working examples
