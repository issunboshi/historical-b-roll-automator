# YouTube Toolkit: Service Integration Spec

**Version:** 1.0
**Date:** 2026-02-03
**Status:** On hold — spec for future monorepo, not yet implemented
**Archived:** 2026-02-10
**Purpose:** Shared spec for integrating services into the YouTube Toolkit monorepo

---

## Overview

The YouTube Toolkit is a local-first, polyglot monorepo containing tools for YouTube video production:

| Service | Language | Purpose |
|---------|----------|---------|
| b-roll-finder | Python | Extract entities → Wikipedia images → NLE timeline |
| video-selects | TypeScript | Classify takes (select/mistake/maybe) → timeline markers |
| outliers | Node.js | Find high-performing videos for research |
| motion-graphics | SvelteKit | Generate motion graphics from prompts |
| research-tool | Go | Research and ideation support |
| **dashboard** | Tauri + Svelte | Unified UI, project coordination |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Tauri Desktop App                            │
│                  (Dashboard + Coordinator)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Traefik                                  │
│                     (localhost:8080)                             │
│   Routes: /api/broll/*, /api/selects/*, /api/outliers/*, etc.  │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │ Service │  ◄───►  │ Service │  ◄───►  │ Service │
   │  :800x  │         │  :800x  │         │  :800x  │
   └─────────┘         └─────────┘         └─────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
              ┌──────────────┴──────────────┐
              ▼                             ▼
     ┌───────────────┐             ┌───────────────┐
     │   Postgres    │             │ Shared Volume │
     │   :5432       │             │  /projects/   │
     └───────────────┘             └───────────────┘
```

---

## What Each Service Must Implement

### 1. REST API

Every service must expose a REST API (not just CLI).

**Required endpoints:**

```
GET  /health              → { "status": "ok", "service": "<name>", "version": "<semver>" }
GET  /info                → { "name": "...", "version": "...", "endpoints": [...] }
POST /api/v1/<operation>  → Service-specific operations
```

**Standards:**
- Version prefix: `/api/v1/`
- JSON request/response bodies
- OpenAPI spec generated from code (not hand-written)
- Async operations return job ID, poll for status

**Example async pattern:**

```
POST /api/v1/pipeline/start
  → { "job_id": "abc-123", "status": "pending" }

GET  /api/v1/pipeline/{job_id}
  → { "job_id": "abc-123", "status": "running", "progress": 0.45 }

GET  /api/v1/pipeline/{job_id}/result
  → { "job_id": "abc-123", "status": "completed", "output": {...} }
```

### 2. OpenAPI Spec

Generate OpenAPI 3.0+ spec automatically:

| Language | Tool |
|----------|------|
| Python | FastAPI auto-generates at `/openapi.json` |
| TypeScript | tsoa, or export from Zod schemas |
| Go | swaggo/swag, or oapi-codegen |
| Node.js | express-openapi-validator, or Fastify |

Specs are collected in `packages/api-specs/` for client generation.

### 3. Docker Support

Each service needs a `Dockerfile`:

```dockerfile
# Example structure
FROM <base-image>
WORKDIR /app
COPY . .
RUN <build-command>
EXPOSE <port>
HEALTHCHECK CMD curl -f http://localhost:<port>/health || exit 1
CMD ["<start-command>"]
```

**Labels for Traefik:**

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.<service>.rule=PathPrefix(`/api/<prefix>`)"
  - "traefik.http.services.<service>.loadbalancer.server.port=<port>"
```

### 4. Environment Variables

All services read from unified `.env`:

```bash
# API Keys (shared)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
YOUTUBE_API_KEY=
WIKIPEDIA_API_ACCESS_TOKEN=

# Infrastructure
DATABASE_URL=postgresql://toolkit:toolkit@postgres:5432/youtube_toolkit
PROJECTS_DIR=/projects

# Service-specific (prefixed)
BROLL_CACHE_TTL=604800
SELECTS_MODEL=claude-3-sonnet
```

### 5. Database Access (Optional)

If service needs persistent state beyond files:

- Use Postgres via `DATABASE_URL`
- Each service owns its schema (e.g., `broll.*`, `selects.*`)
- Migrations in `migrations/` directory
- Use service-appropriate ORM/query builder

### 6. CLI Wrapper (Optional but Recommended)

Keep CLI as thin wrapper over API client:

```python
# Python example
@cli.command()
def pipeline(srt: Path, output_dir: Path):
    """Run the b-roll pipeline."""
    client = BRollClient(base_url="http://localhost:8001")
    job = client.start_pipeline(srt_path=str(srt), output_dir=str(output_dir))

    while job.status not in ("completed", "failed"):
        job = client.get_status(job.job_id)
        click.echo(f"Progress: {job.progress:.0%}")
        time.sleep(1)
```

---

## Port Assignments

| Service | Port | Traefik Prefix |
|---------|------|----------------|
| b-roll-finder | 8001 | `/api/broll` |
| video-selects | 8002 | `/api/selects` |
| outliers | 8003 | `/api/outliers` |
| motion-graphics | 8004 | `/api/mograph` |
| research-tool | 8005 | `/api/research` |
| dashboard (Tauri) | 3000 | `/` |
| Traefik | 8080 | - |
| Traefik Dashboard | 8081 | - |
| Postgres | 5432 | - |

---

## Inter-Service Communication

Services can call each other via Traefik:

```python
# From video-selects, call b-roll-finder
response = requests.post(
    "http://traefik:8080/api/broll/v1/pipeline/start",
    json={"srt_path": "/projects/my-video/transcript.srt"}
)
```

Or directly (within Docker network):

```python
response = requests.post(
    "http://b-roll-finder:8001/api/v1/pipeline/start",
    json={"srt_path": "/projects/my-video/transcript.srt"}
)
```

---

## Migration Checklist

When preparing a service for the monorepo:

- [ ] REST API implemented (not just CLI)
- [ ] `/health` endpoint returns service name and version
- [ ] `/info` endpoint lists available operations
- [ ] OpenAPI spec generated at `/openapi.json`
- [ ] Dockerfile created and tested
- [ ] Traefik labels configured
- [ ] Environment variables documented
- [ ] Long-lived feature branch created (don't break main)
- [ ] CLI wrapper calls API (optional)
- [ ] Database migrations if using Postgres (optional)

---

## Development Strategy

### Long-Lived Feature Branches

All services develop API layer on feature branches:

```
main                    ← Stable, working CLI
  └── feature/api-layer ← API implementation
```

**Rules:**
1. `main` stays functional for current users
2. Feature branches can live for weeks/months
3. Merge only when new approach validated end-to-end
4. Tag releases before major changes

---

## Timeline Outputs

All services that generate timeline data should use the shared `nle-timeline` package (once built) or output to these formats:

| Format | Extension | Used By |
|--------|-----------|---------|
| FCP 7 XML | `.xml` | DaVinci Resolve, older FCP |
| FCPXML | `.fcpxml` | Final Cut Pro X |
| Premiere XML | `.prproj` or `.xml` | Adobe Premiere |
| EDL | `.edl` | Universal, limited features |

---

## Example: Adding API to Existing CLI

### Before (CLI only)

```
my-service/
├── src/
│   ├── main.ts          # CLI entry point
│   ├── commands/
│   └── lib/             # Business logic
├── package.json
└── README.md
```

### After (CLI + API)

```
my-service/
├── src/
│   ├── cli.ts           # CLI (thin wrapper)
│   ├── api/
│   │   ├── server.ts    # Express/Fastify app
│   │   ├── routes/
│   │   │   ├── health.ts
│   │   │   └── operations.ts
│   │   └── openapi.ts   # Spec generation
│   ├── core/            # Business logic (shared)
│   └── models/          # Types/schemas
├── Dockerfile
├── package.json
└── README.md
```

**Key:** Extract business logic to `core/`, have both CLI and API call it.

---

## Questions?

This spec is a living document. Update as patterns evolve.

*Created: 2026-02-03*
