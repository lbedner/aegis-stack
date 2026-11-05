# HTTPS and domains

HTTPS comes from the [ingress component](../components/ingress.md): Traefik in
front of the app, with certificates from Let's Encrypt, renewed on their own.

## A name without a domain

`aegis deploy-provision` without `--domain` gives the app an `sslip.io` name
from its address (`203-0-113-7.sslip.io`) and turns on HTTPS for it, so a first
deploy needs no domain at all.

## Your own domain

With `--domain`, provisioning points the name at the server through your DNS
provider (Porkbun or Cloudflare; their keys are on
[Cloud accounts and keys](cloud.md)), and waits for it to resolve before the
first certificate request, so Let's Encrypt does not fail on it:

```bash
aegis deploy-provision --domain app.example.com --dns cloudflare
```

On a server you set up yourself, turn HTTPS on and point the name by hand:

```bash
# 1. Enable TLS on the project
aegis ingress-enable --domain example.com --email admin@example.com

# 2. Point the domain's A record at the server's IP

# 3. Deploy: the certificate is issued on the first request
aegis deploy
```

!!! warning "DNS must be configured first"
    Let's Encrypt validates the domain over an HTTP challenge, so its A record must point at the server **before** the first certificate is requested.

`aegis ingress-enable` adds the ingress component if it is missing, configures
`traefik/traefik.yml` with the HTTPS entrypoint and ACME resolver, updates the
compose labels for TLS routing, adds the `traefik-letsencrypt` volume for the
certificates, and redirects HTTP to HTTPS. All options:
[`aegis ingress-enable`](../cli-reference.md#aegis-ingress-enable).

After the deploy:

- `http://example.com` redirects to `https://example.com`
- Certificates renew before they expire
- Certificates persist in the `traefik-letsencrypt` volume, and deploys never
  delete Traefik's certificate store (re-issuing can hit Let's Encrypt's rate
  limits)

## The certificate's email

Let's Encrypt needs an address: `--email`, or the one TLS was turned on with,
or the project's `author_email` when it is not the generated placeholder.
Without one, provisioning stops before creating anything. The address is kept
in `.aegis/deploy.yml` (git-ignored), never in a committed file: each deploy
stamps it into the server's `.env` as `ACME_EMAIL`, and Traefik fills its
config in from that when it starts.

A project whose `docker-compose.prod.yml` takes its host from `${DOMAIN}` is
left as it is: each deploy stamps what provisioning recorded into the server's
`.env`, the server's name as `DOMAIN`, the certificate's address as
`ACME_EMAIL`, and `--allowlist` as `ADMIN_IP_ALLOWLIST`. Any other project has
HTTPS rendered into its files for the name, as `aegis ingress-enable` does.

## Who reaches Overseer

A deployed Overseer and admin paths admit only private networks until your
address is in `ADMIN_IP_ALLOWLIST` (`--allowlist` at provisioning, or the
server's env). See [Ingress](../components/ingress.md) for the admin
protection.
