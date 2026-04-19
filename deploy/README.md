# Production deploy

VPS + Caddy reverse proxy. Caddy handles TLS via Let's Encrypt; all
other services stay on the internal `natson` docker network.

## Prerequisites

1. A VPS (Ubuntu 22.04+ / Debian 12+ is fine). 2 vCPU / 4 GB RAM is
   comfortable; 1 vCPU / 2 GB works if you cap `MAX_PARALLEL_JOBS=1`.
2. Docker + docker compose plugin installed (`curl -fsSL
   https://get.docker.com | sh`).
3. A DNS A record for your domain pointing at the VPS's public IP,
   **resolving before you boot the stack** (Caddy's ACME challenge
   fails without it).
4. Ports 80, 443, and 443/udp open on the VPS firewall.

## First-time bootstrap

```bash
# 1. Get the code onto the box.
git clone https://github.com/<you>/natsonhotels.git /srv/natsonhotels
cd /srv/natsonhotels

# 2. Create the production .env from the template, fill in real values.
cp .env.production.example .env
$EDITOR .env     # DOMAIN, passwords, Resend key, Lighthouse creds

# 3. Pull the pre-built images from GHCR (CI pushes on every merge to
#    main). Alternative: build locally with `docker compose build`.
docker compose \
    -f docker-compose.yml \
    -f deploy/docker-compose.prod.yml \
    pull

# 4. Apply DB migrations + bootstrap app-tier roles.
docker compose up -d postgres
./db/migrate.sh up
./db/bootstrap-app-roles.sh

# 5. Bring up the full stack.
docker compose \
    -f docker-compose.yml \
    -f deploy/docker-compose.prod.yml \
    up -d

# 6. Watch Caddy's log until "certificate obtained successfully" lands.
docker compose logs -f caddy | grep -E '(cert|obtained|error)'
```

The app is live at `https://${DOMAIN}/` once Caddy finishes its ACME
dance (usually under a minute).

## Upgrades

```bash
cd /srv/natsonhotels
git pull
docker compose \
    -f docker-compose.yml \
    -f deploy/docker-compose.prod.yml \
    pull web jobs-api scraper browser-api

# Apply any pending migrations.
./db/migrate.sh up

docker compose \
    -f docker-compose.yml \
    -f deploy/docker-compose.prod.yml \
    up -d
```

## Local TLS smoke test

Before pushing to the VPS, confirm the overlay parses and web survives
the port-removal:

```bash
docker compose \
    -f docker-compose.yml \
    -f deploy/docker-compose.prod.yml \
    config | head -40
```

If you want a local HTTPS dry-run, uncomment the `localhost { tls
internal }` block in `deploy/Caddyfile` and trust Caddy's local CA:

```bash
sudo cp "$(docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt)" \
    /usr/local/share/ca-certificates/caddy-local.crt
sudo update-ca-certificates
```

## Backups

- `./db/bootstrap-app-roles.sh` and `./db/migrate.sh` are the only
  state-mutating commands you should run manually.
- DB: cron a `pg_dump -Fc` into `/srv/natsonhotels/backups/` daily;
  rotate via logrotate. The `backups/` dir is already gitignored.
- `session_vol` (holds `session.json` + per-job logs) is a docker
  named volume; `docker run --rm -v session_vol:/data …` to snapshot
  if you care about the login cookie + job log history.

## Rollback

```bash
# Pull a specific sha tag instead of :latest.
docker compose pull web:<sha>
docker compose up -d
```

GHCR keeps every commit-sha tag (see `.github/workflows/ci.yml`
`build-images` job metadata), so any past commit is reachable.

## Things to NOT do

- Don't expose port 5432 or 8770 on the VPS. The base compose file
  already dropped those `ports:` blocks; keep it that way.
- Don't let `RESEND_API_KEY` be empty in prod — signups will stall on
  the verification step with no way for users to complete onboarding.
  The dev fallback (log-to-stdout) is intentionally not a prod path.
- Don't reuse `BETTER_AUTH_SECRET` across environments. Rotating it
  invalidates all sessions (which is sometimes what you want).
