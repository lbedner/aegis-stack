# Configuration

All Insights configuration is done through environment variables in your `.env` file.

## GitHub Configuration

```bash
# Required for GitHub Traffic and Stars collectors
INSIGHT_GITHUB_TOKEN=ghp_your_personal_access_token
INSIGHT_GITHUB_OWNER=your-username
INSIGHT_GITHUB_REPO=your-repo

# Collection interval (hours)
INSIGHT_COLLECTION_GITHUB_HOURS=6
```

### Token requirements

The GitHub token needs `repo` scope for traffic data access. Stars data requires the `read:user` scope for profile fetching.

## PyPI Configuration

```bash
# Required for PyPI collector
INSIGHT_PYPI_PACKAGE=your-package-name

# Collection interval (hours)
INSIGHT_COLLECTION_PYPI_HOURS=24
```

No API key needed - PyPI data is queried from the public ClickHouse endpoint.

## Plausible Configuration

```bash
# Required for Plausible collector
INSIGHT_PLAUSIBLE_API_KEY=your_plausible_api_key
INSIGHT_PLAUSIBLE_SITES=your-site.com

# Collection interval (hours)
INSIGHT_COLLECTION_PLAUSIBLE_HOURS=1
```

### Multiple sites

Comma-separate multiple site IDs:

```bash
INSIGHT_PLAUSIBLE_SITES=docs.example.com,blog.example.com
```

### API key

Generate at Plausible dashboard > Settings > API Keys. Requires read access.

## Reddit Configuration

No configuration needed. Reddit posts are tracked on-demand via the CLI:

```bash
my-app insights reddit add https://reddit.com/r/subreddit/comments/id/title
```

## Collection Intervals

Each source has a configurable collection interval. The scheduler runs collections automatically.

| Source | Default | Env Variable | Notes |
|--------|---------|-------------|-------|
| GitHub Traffic | 6h | `INSIGHT_COLLECTION_GITHUB_HOURS` | Must run within 14 days or data is lost |
| GitHub Stars | 24h | Fixed | Stars don't change frequently |
| GitHub Events | 24h | Fixed | ClickHouse data updates daily |
| PyPI | 24h | `INSIGHT_COLLECTION_PYPI_HOURS` | ClickHouse has ~2 day lag |
| Plausible | 24h | `INSIGHT_COLLECTION_PLAUSIBLE_HOURS` | Lower intervals (1h) useful for near-real-time data |
| Reddit | On-demand | N/A | Manual via CLI |

### Staleness detection

Sources are considered stale after 3x their configured interval. A stale source triggers a warning badge on the Insights card in Overseer.

## Scheduler Setup

For automated collection, include the scheduler component. The collector jobs are listed in `SERVICE_JOBS` (`app/components/scheduler/jobs.py`), run on the worker when the project has one, and are re-applied from code on every scheduler restart, so a normal redeploy is enough to pick them up.

## Database

Insights requires the database component. All data is stored in SQLite (default) or PostgreSQL.

### Tables created

| Table | Purpose |
|-------|---------|
| `insight_source` | Source registry (GitHub, PyPI, etc.) |
| `insight_metric_type` | Metric type definitions |
| `insight_metric` | Time-series data with JSONB metadata |
| `insight_record` | All-time records (reserved for future use) |
| `insight_event` | Timeline events (releases, stars, milestones) |

Tables are created automatically via the database init hook. Seed data (sources + metric types) is populated on first startup.
