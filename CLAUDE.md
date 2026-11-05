# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mandatory first step

Before responding to ANY user message, read [`AGENT_GUIDE.md`](AGENT_GUIDE.md). It is the complete operating guide and agent contract. It contains routing rules that determine your first action based on what the user asked. Skipping it will cause you to take the wrong action.

This CLAUDE.md is intentionally thin by design: all platform-specific agent files (CLAUDE.md, CODEX.md, CURSOR.md, COPILOT.md) point to `AGENT_GUIDE.md` and [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) instead of duplicating their content. Use this file for the repo-specific commands and architectural context that future instances need to operate productively; use `AGENT_GUIDE.md` for the agent contract, stage director skills, protocols, and tool usage rules.

## Development commands

All commands run from the repo root. Python commands assume an activated virtual environment (`.venv`); `make` handles creation automatically.

| Command | What it does |
|---|---|
| `make setup` | One-command setup: create `.venv`, install Python deps, install Remotion composer (`npm install`), install Piper TTS, cache-warm HyperFrames, copy `.env.example` to `.env`. Run this first after cloning. |
| `make install` | Install Python dependencies only (`pip install -r requirements.txt`). |
| `make install-dev` | Install dev dependencies (`pip install -r requirements-dev.txt`). |
| `make install-gpu` | Install GPU/local video generation deps (`requirements-gpu.txt` + `diffusers transformers accelerate`). |
| `make test` | Run the full test suite: `python -m pytest tests/ -v`. |
| `make test-contracts` | Run contract tests only: `python -m pytest tests/contracts/ -v`. |
| `make lint` | Byte-compile the core Python modules (`py_compile` on `base_tool.py`, `tool_registry.py`, `cost_tracker.py`, `composition_validator.py`). |
| `make preflight` | Print the full provider menu (every tool grouped by capability, available/unavailable). Run before any creative work to see the real capability envelope. |
| `make demo` | Render zero-key demo videos (Remotion only, no API keys needed): `python render_demo.py`. Use `make demo --list` to list demos, or `make demo <name>` for one. |
| `make hyperframes-doctor` | Validate the HyperFrames runtime floor (node/ffmpeg/npx + `hyperframes doctor`). |
| `make hyperframes-warm` | Refresh the HyperFrames npx cache to latest. |
| `make clean` | Remove `__pycache__` and `.pyc` files (excluding venvs). |

### Running a single test

```bash
# Run one test file
python -m pytest tests/contracts/test_pipeline_catalog.py -v

# Run one specific test
python -m pytest tests/contracts/test_pipeline_catalog.py::test_pipelines_have_manifests -v

# Run a directory
python -m pytest tests/contracts/ -v

# A test that calls a live, billable API is skipped by default; opt in deliberately:
OPENMONTAGE_ALLOW_NETWORK=1 python -m pytest tests/tools/test_atlas_video.py -m live_api
```

Tests that open non-loopback network sockets are blocked at the socket layer by `tests/conftest.py` (provider APIs bill per call). Live-api tests carry the `live_api` marker and require `OPENMONTAGE_ALLOW_NETWORK=1`. Tests shelling out to node/ffmpeg/npx are outside the guard — do not call paid APIs from a subprocess in tests.

### Environment

Copy `.env.example` to `.env` and add API keys. Every key is optional — zero-key operation works with Piper TTS, Archive.org/NASA/Wikimedia footage, Pexels/Pixabay/Unsplash stock, Remotion composition, and FFmpeg post-production. See [`docs/PROVIDERS.md`](docs/PROVIDERS.md) for the full provider setup guide with pricing and free tiers.

## High-level architecture

OpenMontage is an **agent-first, instruction-driven video production system**. The AI agent IS the orchestrator — there is no Python orchestrator, reviewer, or handler. Python exists only for tools and persistence. All orchestration, creative decisions, review, and stage transitions live in readable instruction files (YAML manifests + Markdown skills) that the agent follows.

```
You: "Make an explainer video"
  |
  v
Agent reads pipeline manifest (YAML) — stages, tools, review criteria, gates
  |
  v
Agent reads stage director skill (Markdown) — HOW to execute each stage
  |
  v
Agent calls Python tools — scored provider selection ranks every tool across 7 dimensions
  |
  v
Agent self-reviews using the reviewer meta skill
  |
  v
Agent checkpoints state (JSON) — resumable, with decision log and cost snapshot
  |
  v
Agent presents for human approval — creative gates pause for sign-off
  |
  v
Pre-compose validation gate — delivery promise, slideshow risk, renderer governance
  |
  v
Render (Remotion or FFmpeg) — composition engine matched to visual grammar
  |
  v
Post-render self-review — ffprobe, frame extraction, audio analysis, promise verification
  |
  v
Final video output — only if self-review passes
```

### Three instruction layers

| Layer | Directory | Role |
|---|---|---|
| Layer 1 — "What exists" | `tools/` + `pipeline_defs/` | Executable capabilities (`BaseTool` subclasses) + orchestration manifests |
| Layer 2 — "How to use it" | `skills/` | OpenMontage conventions: pipeline stage directors, meta skills (reviewer, checkpoint-protocol), creative techniques |
| Layer 3 — "How the technology works" | `.agents/skills/` | Vendor/technology knowledge packs (provider-specific prompting, GSAP, framer-motion, Manim, etc.) |

Each tool's `agent_skills[]` field bridges Layer 1 → Layer 3. Read Layer 1 to know what's available, Layer 2 to know how OpenMontage wants it used, and Layer 3 before calling any generation tool.

### Core pipeline

Every production follows the same state machine:

```
research -> proposal -> script -> scene_plan -> assets -> edit -> compose -> publish
```

Each stage has a **director skill** in `skills/pipelines/<pipeline>/<stage>-director.md` that the agent must read before doing work in that stage. Each stage produces one canonical artifact (`brief`, `script`, `scene_plan`, `asset_manifest`, `edit_decisions`, `render_report`, `publish_log`) validated against JSON schemas in `schemas/artifacts/`.

### Project workspace

Every production run creates a gitignored workspace under `projects/<project-id>/`:

```
projects/<project-id>/
├── artifacts/          # JSON artifacts per stage (research_brief, script, scene_plan, ...)
├── assets/
│   ├── images/         # Generated images (PNG)
│   ├── video/          # Generated video clips (MP4)
│   ├── audio/          # Narration + final mix
│   └── music/          # Background music
├── checkpoints/        # checkpoint_<stage>.json + history/
└── renders/
    └── final.mp4       # The deliverable
```

All tools must write outputs under `projects/<project-id>/` via an explicit `output_path`. Assets written to the repo root, cwd, or temp dirs are invisible to the Backlot board and violate the workspace contract.

### Key infrastructure files

| File | Purpose |
|---|---|
| `lib/checkpoint.py` | Checkpoint writer/reader; enforces `human_approval_default` gates per stage |
| `lib/pipeline_loader.py` | Pipeline manifest loading and helpers |
| `lib/config_model.py` | Runtime config loader (Pydantic) |
| `lib/media_profiles.py` | Platform render profiles (YouTube, TikTok, Reels, etc.) |
| `tools/base_tool.py` | `BaseTool` contract — every tool inherits this; call via `.execute(params)` |
| `tools/tool_registry.py` | Tool discovery and reporting (`discover()`, `provider_menu_summary()`, `capability_catalog()`, `provider_catalog()`) |
| `tools/cost_tracker.py` | Budget governance: estimate → reserve → reconcile |
| `tools/video/video_compose.py` | Runtime-aware composition orchestrator — routes to Remotion / HyperFrames / FFmpeg based on `edit_decisions.render_runtime` |
| `tools/video/video_stitch.py` | Multi-clip assembly (stitch, spatial, validate, preview) |
| `schemas/artifacts/` | JSON Schemas for canonical artifacts |
| `schemas/pipelines/pipeline_manifest.schema.json` | Pipeline manifest schema |

### Composition runtimes

`video_compose` has three parallel runtimes (not ranked); the choice is locked at proposal and carried through `edit_decisions`:

- **FFmpeg** — video-only cuts, concat, trim, subtitle burn. Always available (`ffmpeg` binary).
- **Remotion** — React-based programmatic video (still images → animated video, text cards, stat cards, charts, word-level captions, TalkingHead). Requires Node.js + `remotion-composer/` + `node_modules`. Components live in `remotion-composer/src/components/`.
- **HyperFrames** — HTML/CSS/GSAP programmatic video (kinetic typography, product promos, launch reels, SVG character rigs). Consumed via `npx hyperframes`; requires Node.js ≥ 22 + FFmpeg.

`render_runtime` selection is a hard governance rule: present both runtimes to the user at proposal when both are available, log the full shortlist in `decision_log`, and never silently swap runtimes.

### Available pipelines

`animated-explainer`, `talking-head`, `screen-demo`, `clip-factory`, `podcast-repurpose`, `cinematic`, `animation`, `character-animation`, `hybrid`, `avatar-spokesperson`, `localization-dub`, `documentary-montage`, `framework-smoke` (test). Manifests live in `pipeline_defs/`. Beta pipelines (`talking-head`, `clip-factory`, `podcast-repurpose`, `character-animation`, `localization-dub`, `documentary-montage`) work but have rough edges — mention this when selected.

### Backlot (living storyboard)

A read-only local board derived entirely from `projects/<id>/` files — no agent involvement:

```bash
python -m backlot open <project-id>   # one production's live board
python -m backlot open                # library view (all projects)
python scripts/backlot_simulate_run.py  # simulated run without a real production
```

Stage states, gates, script, filmstrip, events, and cost meter all come from checkpoint files and artifacts on disk.

### Cursor / Copilot rules

The Cursor rule (`.cursor/rules/openmontage.mdc`) and the Copilot/GitHub/GitLab agent files (`.github/copilot-instructions.md`, `COPILOT.md`, `CURSOR.md`, `CODEX.md`, `.windsurfrules`) all contain a single mandatory directive: read `AGENT_GUIDE.md` before acting; all instructions live there. There are no additional project-specific rules in those files beyond that routing.

### Important README points

- OpenMontage can make **real video video** (retrieved motion clips edited into a timeline), not just Ken Burns over stills — see the README's "Important distinction."
- Prerequisites: Python 3.10+, FFmpeg, Node.js 18+, an AI coding assistant.
- Music is mandatory at proposal time: check `music_library/`, royalty-free search, or generation APIs before asset generation.
- Style playbooks (`clean-professional`, `premium-minimalist`, `flat-motion-graphics`, `minimalist-diagram`, `ink-sketch`) control typography, color, motion, audio, and quality rules.
- Budget controls: estimate before execution, reserve budget, reconcile after, configurable modes (observe/warn/cap), per-action approval threshold (default $0.50), total cap (default $10).

## Conventions to remember

- **No ad-hoc scripts calling tools directly.** All production goes through pipeline stages with director skills (Rule Zero in `AGENT_GUIDE.md`).
- **No generation tool calls without reading its Layer 3 skill** (the tool's `agent_skills[]` pointer in `.agents/skills/`).
- **No hardcoded provider names, API key names, or setup URLs.** Read them from the registry's `install_instructions`/`dependencies` fields.
- **Tool class naming:** PascalCase without a "Tool" suffix (e.g. `VideoCompose`, not `VideoComposeTool`). Module `tools.video.video_compose` → class `VideoCompose`.
- **Tool call convention:** `.execute(params_dict)` returns a `ToolResult` with `.success`, `.data`, `.error` — not `.run()`.
- **Adding a new tool:** inherit `BaseTool`, place in the correct `tools/<capability>/` package, set all contract fields, implement `execute()`, let the registry auto-discover it.
- **Adding a new pipeline:** YAML manifest in `pipeline_defs/` + stage director skills in `skills/pipelines/<pipeline>/` + contract tests in `tests/contracts/`.
