"""The stamp signatures: proof-objects for every shipped migration.

The startup hook re-adopts a persisted database by checking, per pending
migration (``NNN_<service>.py``), whether its signature object already
exists - and stamping instead of replaying DDL. A migration that ships
WITHOUT an entry opts out of that recovery and re-creates the
finance_icon incident: alembic_version lags, the upgrade replays, and the
database logs "already exists" on every boot until someone stamps by
hand. Guarded by ``tests/test_migration_signatures.py``.

Forms:
- ``("table", name)`` - table exists (CREATE TABLE migrations). Names may
  be schema-qualified; matching tolerates the bare name on engines
  without schemas (SQLite).
- ``("column", table, col)`` - column exists (ALTER TABLE migrations).
- ``("foreign_key", table, col)`` - an FK constraint covers the column
  (FK-only migrations, e.g. payment_auth_link).
"""

SERVICE_MIGRATION_SIGNATURES: dict[str, tuple[str, ...]] = {
    "ai": ("table", "llm_vendor"),
    "ai_agents": ("table", "agent"),
    "agent_code_mode": ("column", "agent", "code_mode"),
    "ai_sentiment": ("table", "sentiment_analysis"),
    "ai_voice": ("table", "voice_usage"),
    "auth": ("table", "user"),
    "auth_org": ("table", "organization"),
    "auth_rbac": ("column", "user", "role"),
    "auth_tokens": ("table", "refresh_token"),
    "blog": ("table", "blog_post"),
    # insight_source, not project: the project table only exists in the
    # per-user shape, insight_source in both.
    "insights": ("table", "insight_source"),
    "payment": ("table", "payment_provider"),
    "payment_auth_link": ("foreign_key", "payment_customer", "user_id"),
    "finance": ("table", "finance.finance_account"),
    "finance_budget_payee": ("column", "finance.finance_budget_category", "payee_key"),
    "finance_auth_link": ("foreign_key", "finance.finance_account", "owner_user_id"),
    "finance_icon": ("table", "finance.finance_icon"),
    "secured_debt": (
        "column",
        "finance.finance_liability_detail",
        "secured_by_account_id",
    ),
    "scheduler": ("table", "scheduler.job_execution"),
}
