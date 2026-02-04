# YouTube Video Production Toolkit: Architecture Exploration

**Date:** 2026-02-03
**Status:** Answers received, recommendations updated
**Context:** Thinking through how b-roll-finder could exist in a unified toolkit

---

## Current State Discovery

### The Ecosystem (5 YouTube-related tools identified)

| Tool | Language | Interface | Purpose |
|------|----------|-----------|---------|
| **b-roll-finder-app** | Python 3.13 | CLI + API (WIP) | Extract entities → Wikipedia images → NLE timeline |
| **youtube-video-selects-finder** | TypeScript | CLI + TUI (Ink) | Classify takes (select/mistake/maybe) → EDL/FCPXML |
| **youtube-outliers** | Node.js/Express | Web UI + API | Find high-performing videos for research |
| **motion-graphics-generator** | SvelteKit + Supabase | Web UI | Generate motion graphics from prompts |
| **video-research-and-ideation-tool** | Go | (early stage) | Research and ideation support |

### What I Found in `./src` (Direction of Travel)

You've already started building toward API-first architecture:

```
src/
├── api/
│   ├── main.py          # FastAPI app with CORS, versioned routes
│   └── routes/
│       ├── health.py     # Health check endpoint
│       ├── disambiguation.py  # POST /api/v1/disambiguate
│       └── pipeline.py   # Async pipeline execution with status polling
├── core/
│   ├── disambiguation.py # Core business logic
│   └── review.py         # (review functionality)
└── models/
    ├── entity.py         # Pydantic models (Entity, Occurrence, etc.)
    ├── disambiguation.py # Request/response models
    └── pipeline.py       # Pipeline config, status, result models
```

**Key observations:**
- FastAPI with Pydantic models (good for OpenAPI schema generation)
- Async pipeline with background tasks and status polling
- Clean separation: models → core logic → API routes
- Version prefix `/api/v1` already in place
- CORS configured for cross-origin access

---

## Cliff's Answers (2026-02-03)

| # | Question | Answer |
|---|----------|--------|
| 1 | Which tools are "core"? | **All tools are core** - no distinction between editing and pre-production |
| 2 | Unified UI role? | **Dashboard, coordination, project management** |
| 3 | Will tools call each other? | **Yes, in many cases** |
| 4 | Deployment model? | **Local-only** - avoid transferring large video files |
| 5 | Build system investment? | **Open to ideas** |
| 6 | Shared artifacts or API calls? | **API calls mainly** - artifacts only if advantageous, API-first |
| 7 | Unified timeline generation? | **Multi-NLE support** - DaVinci, Final Cut, and Premiere |
| 8 | Unified API key config? | **Yes** |

### Key Implications

1. **All tools tightly integrated** → Leans toward monorepo (Approach A)
2. **Inter-service API calls** → Need service discovery or API gateway pattern
3. **Local deployment** → Docker Compose is the natural choice
4. **API-first** → Each tool exposes REST API, CLI is thin wrapper
5. **Multi-NLE** → Need abstraction layer for timeline formats (FCP XML, Premiere XML, EDL)
6. **Unified config** → Central secrets/config management

---

## Revised Architecture Recommendation

Given your answers, I now recommend **Approach A: Polyglot Monorepo** with a **local-first, API-gateway architecture**.

### Proposed Structure

```
youtube-toolkit/
├── apps/
│   ├── b-roll-finder/           # Python - this repo
│   ├── video-selects/           # TypeScript
│   ├── outliers/                # Node.js
│   ├── motion-graphics/         # SvelteKit
│   ├── research-tool/           # Go
│   └── dashboard/               # Unified UI (Svelte/React)
│
├── packages/
│   ├── nle-timeline/            # Multi-NLE export (shared library)
│   │   ├── python/              # Python bindings
│   │   ├── typescript/          # TS/Node bindings
│   │   └── go/                  # Go bindings
│   ├── transcript-utils/        # SRT parsing (shared)
│   └── api-specs/               # OpenAPI definitions for all services
│
├── config/
│   ├── .env.example             # Unified API keys template
│   └── services.yaml            # Service registry (ports, health checks)
│
├── docker-compose.yml           # Local orchestration
├── docker-compose.dev.yml       # Dev overrides (hot reload)
└── Makefile                     # Unified commands: make start, make test
```

### Local Runtime Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Dashboard UI                              │
│                     (localhost:3000)                             │
│         Coordination / Project Management / Status               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Traefik                                  │
│                     (localhost:8080)                             │
│   Routes: /api/broll/* → :8001, /api/selects/* → :8002, etc.   │
│   Dashboard: localhost:8081                                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  B-Roll API   │    │  Selects API  │    │  Outliers API │
│  Python:8001  │◄──►│    TS:8002    │◄──►│  Node:8003    │
└───────────────┘    └───────────────┘    └───────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
              ┌──────────────┴──────────────┐
              ▼                             ▼
     ┌───────────────┐             ┌───────────────┐
     │   Postgres    │             │ Shared Volume │
     │   :5432       │             │  /projects/   │
     │ (project state│             │  (video files,│
     │  job queues)  │             │   outputs)    │
     └───────────────┘             └───────────────┘
```

### Inter-Service Communication

Since tools will call each other, define clear patterns:

```yaml
# services.yaml - Service Registry
services:
  b-roll-finder:
    port: 8001
    health: /health
    api_prefix: /api/v1

  video-selects:
    port: 8002
    health: /health
    api_prefix: /api/v1

  # ... etc
```

**Example flow: Dashboard orchestrates a project**

```
1. User uploads video + SRT via Dashboard
2. Dashboard calls video-selects API → classify takes
3. Dashboard calls b-roll-finder API → find images for "select" segments
4. Dashboard calls motion-graphics API → generate graphics for intros
5. Dashboard calls b-roll-finder API → generate unified NLE timeline
6. User imports timeline into Premiere/Final Cut/DaVinci
```

---

## Shared Packages

### 1. nle-timeline (Multi-NLE Export)

Abstract timeline generation supporting all major NLEs:

```python
# Python usage
from nle_timeline import Timeline, Clip, Format

timeline = Timeline(name="My Project", fps=24)
timeline.add_clip(Clip(
    start="00:00:10,000",
    end="00:00:15,000",
    media_path="/path/to/image.jpg",
    track=2
))

# Export to any format
timeline.export(Format.FCPXML)      # Final Cut Pro
timeline.export(Format.PREMIERE)    # Premiere Pro XML
timeline.export(Format.RESOLVE)     # DaVinci Resolve (FCP7 XML)
timeline.export(Format.EDL)         # Edit Decision List
```

```typescript
// TypeScript usage
import { Timeline, Clip, Format } from '@youtube-toolkit/nle-timeline';

const timeline = new Timeline({ name: 'My Project', fps: 24 });
timeline.addClip({ start: '00:00:10,000', end: '00:00:15,000', ... });
timeline.export(Format.FCPXML);
```

### 2. transcript-utils (SRT Parsing)

Shared transcript parsing across Python/TS/Go:

```python
from transcript_utils import parse_srt, Cue

cues: list[Cue] = parse_srt("video.srt")
for cue in cues:
    print(f"{cue.start} → {cue.end}: {cue.text}")
```

### 3. Unified Config

```bash
# Single .env file for all services
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
YOUTUBE_API_KEY=...
WIKIPEDIA_API_ACCESS_TOKEN=...

# Project paths (shared volume)
PROJECTS_DIR=/Users/cliff/youtube-projects
```

---

## Migration Path

### Phase 1: API-First for b-roll-finder (Now)
- Complete `./src` implementation
- Generate OpenAPI spec from Pydantic models
- CLI becomes thin wrapper over HTTP client
- Add health check, service metadata endpoint

### Phase 2: Create Monorepo Structure
- Create `youtube-toolkit/` repo
- Move b-roll-finder as first app
- Set up Docker Compose with single service
- Add unified config pattern

### Phase 3: Migrate Second Tool
- Move video-selects-finder into monorepo
- Implement inter-service call (selects → b-roll)
- Validate Docker Compose works with 2 services

### Phase 4: Add Dashboard
- Build minimal dashboard UI
- Project creation, status tracking
- Orchestrate multi-tool workflows

### Phase 5: Continue Migration
- Move remaining tools
- Build shared packages (nle-timeline, transcript-utils)
- Add API gateway for unified routing

---

## Build System Options

For polyglot monorepo with Python, TypeScript, Go, and SvelteKit:

| Option | Complexity | Polyglot Support | Recommendation |
|--------|------------|------------------|----------------|
| **Makefile + Docker Compose** | Low | Good | Start here |
| **Just (justfile)** | Low | Good | Modern Make alternative |
| **Nx** | Medium | Growing | Good if heavy JS/TS |
| **Pants** | High | Excellent | If you need hermetic builds |
| **Bazel** | Very High | Excellent | Overkill for this scale |

**My suggestion:** Start with **Makefile + Docker Compose**. It's simple, well-understood, and sufficient for 5 services. Migrate to Pants later only if you hit scaling issues.

```makefile
# Example Makefile
.PHONY: start stop dev test

start:
	docker-compose up -d

stop:
	docker-compose down

dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

test:
	docker-compose run --rm b-roll-finder pytest
	docker-compose run --rm video-selects npm test
```

### Example docker-compose.yml

```yaml
version: "3.8"

services:
  traefik:
    image: traefik:v3.0
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--entrypoints.web.address=:8080"
    ports:
      - "8080:8080"   # API Gateway
      - "8081:8080"   # Traefik Dashboard
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: toolkit
      POSTGRES_PASSWORD: toolkit
      POSTGRES_DB: youtube_toolkit
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  b-roll-finder:
    build: ./apps/b-roll-finder
    labels:
      - "traefik.http.routers.broll.rule=PathPrefix(`/api/broll`)"
    environment:
      - DATABASE_URL=postgresql://toolkit:toolkit@postgres:5432/youtube_toolkit
    env_file:
      - ./config/.env
    volumes:
      - projects:/projects
    depends_on:
      - postgres

  # video-selects, outliers, etc. follow same pattern...

  dashboard:
    build: ./apps/dashboard
    ports:
      - "3000:3000"
    labels:
      - "traefik.http.routers.dashboard.rule=PathPrefix(`/`)"
    depends_on:
      - traefik
      - postgres

volumes:
  postgres_data:
  projects:
```

---

## Technical Decisions (2026-02-03)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| API Gateway | **Traefik** | Dynamic config, Docker-native, good dashboard |
| Project State | **Postgres** | Robust, shared across services, good tooling |
| Monorepo Timing | **After b-roll-finder API** | Validate pattern first |
| Dashboard Tech | **Tauri + Svelte** | Native desktop, direct filesystem, bundled services |
| Dev Strategy | **Long-lived feature branches** | Keep `main` stable for current CLI users |

### Shared Documentation

See **[YOUTUBE_TOOLKIT_SERVICE_SPEC.md](./YOUTUBE_TOOLKIT_SERVICE_SPEC.md)** for the portable spec to use on other services.

### Dashboard Technology Options

#### Option A: SvelteKit (Recommended)

**Pros:**
- You already use it (motion-graphics-generator)
- Excellent performance, small bundle size
- Server-side rendering built-in
- Good TypeScript support
- SvelteKit 2 is mature and stable

**Cons:**
- Smaller ecosystem than React
- Fewer pre-built component libraries

**Best for:** Fast, lightweight dashboard with custom components

```
apps/dashboard/
├── src/
│   ├── routes/
│   │   ├── +page.svelte        # Dashboard home
│   │   ├── projects/
│   │   └── api/                # BFF endpoints
│   └── lib/
│       └── components/
├── svelte.config.js
└── package.json
```

#### Option B: Next.js (App Router)

**Pros:**
- Largest ecosystem, most component libraries
- Server Components reduce client JS
- Excellent Vercel tooling (if ever go cloud)
- React Server Actions for forms

**Cons:**
- Heavier than SvelteKit
- React complexity (hooks, effects)
- You'd be adding another framework to learn

**Best for:** If you want maximum library availability

#### Option C: Remix

**Pros:**
- Excellent data loading patterns
- Progressive enhancement focus
- Simpler mental model than Next.js
- Great for forms and mutations

**Cons:**
- Smaller ecosystem than Next.js
- Less momentum recently

**Best for:** Form-heavy dashboards with complex data flows

#### Option D: Go + htmx + Templ

**Pros:**
- Single binary deployment
- Extremely fast
- No JS build step
- Matches your Go experience (research-tool)
- htmx for interactivity without SPA complexity

**Cons:**
- Less common pattern, fewer examples
- Limited component ecosystem
- Harder to build rich interactive UIs

**Best for:** If you want minimal dependencies and fast startup

#### Option E: Tauri (Desktop App)

**Pros:**
- Native desktop experience
- Direct filesystem access (no upload needed)
- Can embed Traefik/services
- Uses web frontend (Svelte/React/etc.)

**Cons:**
- More complex distribution
- Platform-specific builds
- Overkill if web UI is sufficient

**Best for:** If you want a polished native app experience

---

### Decision: Tauri

Cliff chose **Tauri** for the dashboard/coordinator app.

**Rationale:**
- Native desktop experience
- Direct filesystem access (no upload dialogs for video files)
- Can bundle/orchestrate services
- Single distributable app
- Web frontend (Svelte) for UI, Rust for system integration

**Frontend for Tauri:** SvelteKit (consistency with motion-graphics, lightweight)

---

## Development Strategy

### Long-Lived Feature Branches

All API/monorepo work happens on feature branches. The existing CLI remains functional on `main` until the new architecture is validated.

```
main                    ← Stable CLI, current users
  └── feature/api-layer ← API implementation for b-roll-finder
  └── feature/monorepo  ← Monorepo structure (later)
```

**Rules:**
1. Never break `main` - CLI must keep working
2. Feature branches can be long-lived (weeks/months)
3. Merge only when new approach is validated end-to-end
4. Other services follow same pattern on their own repos

---

## Next Steps for This Repo

1. **Complete `./src` API implementation**
   - Wire up actual pipeline execution (currently placeholder)
   - Add OpenAPI spec generation
   - Add `/info` endpoint with service metadata

2. **Abstract timeline generation**
   - Current: FCP 7 XML only
   - Add: Format parameter, support FCPXML/Premiere
   - This becomes seed for shared `nle-timeline` package

3. **Prepare for monorepo**
   - Add Dockerfile
   - Add health check endpoint (already have `/health`)
   - Document API contract

---

*Document updated with Cliff's answers. Ready for Phase 1 execution.*
