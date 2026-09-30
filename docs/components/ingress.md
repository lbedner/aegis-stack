# Ingress Component

Reverse proxy and traffic routing with [Traefik](https://traefik.io/traefik/) - automatic service discovery, admin endpoint protection, and optional TLS via Let's Encrypt.

Use `aegis init my-project --components ingress` or add it to an existing project with `aegis add ingress`.

## What Ingress Adds

When you include the ingress component, your project gets:

- **Traefik v3.6 reverse proxy** as a Docker service
- **Automatic service discovery** via Docker labels - no manual routing config
- **Admin endpoint protection** with IP allowlist middleware
- **Optional TLS/HTTPS** via Let's Encrypt certificate automation
- **Health check integration** with the Overseer dashboard
- **Production deployment support** with `docker-compose.prod.yml` overrides

## Generated Files

```
my-project/
├── traefik/
│   └── traefik.yml           # Traefik static configuration
├── scripts/
│   └── server-setup.sh       # Server provisioning script
├── docker-compose.yml         # Updated with Traefik service + labels
├── docker-compose.dev.yml     # Dev overrides (dashboard port exposed)
├── docker-compose.prod.yml    # Prod overrides (no dashboard port)
└── .env.example               # Traefik environment variables
```

## Routing

Traefik uses Docker labels on your services to automatically discover and route traffic. No manual routing configuration needed.

### With a Domain (Host-based routing)

When TLS is enabled with a domain, routing uses `Host()` rules:

```yaml
# Automatically generated labels on webserver service
- "traefik.http.routers.webserver.rule=Host(`example.com`)"
- "traefik.http.routers.webserver.entrypoints=websecure"
- "traefik.http.routers.webserver.tls.certresolver=letsencrypt"
```

### Without a Domain (PathPrefix routing)

Without a domain, routing uses `PathPrefix(/)` for all traffic:

```yaml
- "traefik.http.routers.webserver.rule=PathPrefix(`/`)"
- "traefik.http.routers.webserver.entrypoints=web"
```

## Admin Endpoint Protection

Sensitive endpoints are protected by an IP allowlist middleware. By default, these paths are restricted:

- `/dashboard` - the Flet dashboard
- `/docs` - FastAPI Swagger UI
- `/redoc` - FastAPI ReDoc
- `/openapi.json` - OpenAPI schema

```yaml
# Docker labels on webserver service
- "traefik.http.routers.webserver-admin.middlewares=admin-ipallowlist"
- "traefik.http.middlewares.admin-ipallowlist.ipallowlist.sourcerange=${ADMIN_IP_ALLOWLIST:-127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"
```

The default admits loopback and the private ranges only, so these paths are closed to the public internet until you open them on purpose. Local development still reaches them: Docker hands Traefik your browser's requests from a `172.x` gateway address, which the default covers.

Set `ADMIN_IP_ALLOWLIST` in your `.env` to change who gets in:

```bash
# Default: this machine and private networks
ADMIN_IP_ALLOWLIST=127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

# Only your office IP
ADMIN_IP_ALLOWLIST=203.0.113.50/32

# Everyone, including the public internet (think twice)
ADMIN_IP_ALLOWLIST=0.0.0.0/0
```

The Overseer's Ingress page tags an allowlist that admits every address as **allows all**.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAEFIK_API_URL` | `http://traefik:8080` | Traefik API URL for health checks (Docker internal) |
| `TRAEFIK_API_URL_LOCAL` | `http://localhost:8080` | Traefik API URL for local CLI commands |
| `ADMIN_IP_ALLOWLIST` | loopback and private ranges | CIDR range(s) allowed to access admin endpoints |
| `DOMAIN` | `example.com` | Domain for TLS certificate (only with TLS enabled) |
| `ACME_EMAIL` | - | Email for Let's Encrypt notifications (only with TLS enabled) |

## Dev vs Production

### Development (`docker-compose.dev.yml`)

- Port 80 exposed for HTTP traffic
- Port 8080 exposed for Traefik dashboard
- Port 443 exposed if TLS enabled
- Webserver port not directly exposed (traffic goes through Traefik)

Access the Traefik dashboard at `http://localhost:8080` during development.

### Production (`docker-compose.prod.yml`)

- Port 80 exposed for HTTP traffic
- Port 443 exposed if TLS enabled
- **No port 8080** - dashboard not exposed externally
- Production compose uses `--profile prod`

## Enabling TLS

To add HTTPS to a project with ingress, use the `ingress-enable` command:

```bash
aegis ingress-enable --domain example.com --email admin@example.com
```

This configures:

- HTTP → HTTPS redirect on port 80
- Let's Encrypt certificate automation via ACME HTTP challenge
- `websecure` entrypoint on port 443
- Certificate storage in a Docker volume

See **[Deployment Guide](../deployment/index.md#tlshttps-with-lets-encrypt)** for the full TLS workflow.

## Traefik Configuration

The generated `traefik/traefik.yml` controls Traefik's static configuration:

```yaml
# traefik/traefik.yml (without TLS)
api:
  dashboard: true
  insecure: true

ping:
  entryPoint: traefik

entryPoints:
  web:
    address: ":80"
  traefik:
    address: ":8080"

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: my_project_default

log:
  level: INFO

accessLog: {}
```

With TLS enabled, the configuration adds:

- `websecure` entrypoint on `:443`
- HTTP → HTTPS redirect on the `web` entrypoint
- `certificatesResolvers.letsencrypt` ACME configuration

## Next Steps

- **[Deployment Guide](../deployment/index.md)** - Deploy your project with ingress to a server
- **[Component Overview](./index.md)** - Understanding Aegis Stack's component architecture
- **[Traefik Documentation](https://doc.traefik.io/traefik/)** - Complete Traefik reference
