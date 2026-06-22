# Skill Evolution — Architecture Design

## Core Concept

**Automatically discover reusable workflow patterns** from Hermes session history and precipitate them into Hermes Skills.

Not simple "keyword matching" — but a three-dimensional analysis based on **tool call signatures + user intent + sequence patterns**.

## Data Flow

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  1. Case Miner   │ ──→ │  2. Skill Forge  │ ──→ │  3. Validator    │ ──→ │  4. Presenter    │
│                  │     │                  │     │                  │     │                  │
│ SessionDB →      │     │ Case cluster →   │     │ Skill draft →    │     │ Report →         │
│ tool signatures  │     │ LLM analysis →   │     │ Test scenario →  │     │ User approval    │
│ user intents     │     │ SKILL.md draft   │     │ execution        │     │ skill creation   │
│ sequence mining  │     │                  │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
        │                        │                        │                        │
        ▼                        ▼                        ▼                        ▼
   ~/.hermes/agent/       SKILL.md draft           test output              skill_manage()
   cases/{date}_{name}.md                           in ~/.hermes/agent/
                                                     tests/{name}/
```

## Module Design

### 1. Case Miner (`miner.py`)

**Input**: SessionDB (Hermes session database)
**Output**: Structured case files

#### Feature Extraction Dimensions

| Dimension | Method | Weight |
|:---|:---|:---:|
| Tool call signature | Tool category bigram sequence (terminal→terminal→browser = "shell-work-web") | 0.35 |
| User intent | Extract keywords/themes from first user message | 0.25 |
| Tool co-occurrence | Which tools frequently appear together | 0.20 |
| Session metadata | Duration, token consumption, total tools | 0.10 |
| Message pattern | user→assistant→tool interaction rhythm | 0.10 |

#### Signature Type Definitions

```
SHELL_HEAVY   = terminal ratio > 60%
BROWSER       = browser_navigate/browser_click present
CODE_EXEC     = execute_code present
WEB_RESEARCH  = web_search + web_extract paired
FILE_OPS      = read_file + write_file + patch cycles
MULTI_MODEL   = skill_view + multiple provider calls
CRON_SETUP    = cronjob present
EMAIL         = email_send/email_search present
HYBRID        = 3+ signature types mixed
```

#### Clustering Algorithm

1. **Hard clustering** — Group by dominant signature type (SHELL_HEAVY, BROWSER, etc.)
2. **Soft clustering** — Within-group similarity using TF-IDF on user messages + tool co-occurrence matrix
3. **Threshold** — Cosine similarity > 0.50 considered same cluster

### 2. Skill Forge (`forge.py`)

**Input**: Case cluster
**Output**: SKILL.md draft + validation report

#### Analysis Steps

1. **Common step extraction** — Extract common patterns from tool sequences across multiple cases
2. **Parameter generalization** — Identify fixed parameters vs variable inputs
3. **Pitfall detection** — Count error/rollback patterns across cases
4. **Test scenario generation** — Generate executable test scripts from case data

### 3. Validator (`validator.py`)

**Input**: SKILL.md draft
**Output**: Validation results

#### Validation Methods

- Generate mock session → run skill → verify expected behavior
- Extract related sessions → test if skill correctly handles related queries

### 4. Validation & Install (`validator.py`)

**Input**: Validated skill candidates
**Output**: User-facing report

- Generate report with sample data, use cases, expected behavior
- Support one-click skill creation

## Storage Structure

```
~/.hermes/
├── scripts/
│   ├── mining/               # Pattern discovery
│   │   ├── ARCHITECTURE.md     # This document
│   │   ├── miner.py            # Case extraction + clustering
│   │   ├── forge.py            # LLM skill generation
│   │   ├── validator.py        # Validation pipeline
│   │   └── hook.py             # Incremental cron hook
│   └── skill_evolution.py   # CLI entry (orchestrator)
│
├── agent/
│   ├── cases/                  # Case database
│   │   ├── {date}_{name}.md    # Individual case
│   │   └── .meta.json          # Metadata index
│   └── tests/                  # Test scenarios
│       └── {skill_name}/
│           ├── scenario.py     # Test script
│           └── expected.json   # Expected results
│
└── skills/                     # Final skill output
    └── {skill_name}/SKILL.md
```

## Testing Strategy

1. **Synthetic data tests** — Create mock sessions with known patterns, verify correct extraction
2. **Real data tests** — Run on actual sessions, manually validate clustering quality
3. **End-to-end tests** — Full pipeline from scan to skill creation

## Non-Functional Constraints

- ❌ No modifications to Hermes core code (run_agent.py, hermes_state.py)
- ✅ Standalone CLI entry point
- ✅ All output reviewable and editable
- ✅ No auto-creation of skills — always requires user confirmation

---

## Reflection System

### Purpose

The **Reflection System** maintains Hermes system health — cleaning memory, archiving stale skills, and detecting anomalies. It forms the other half of the Skill Evolution lifecycle:

```
sessions → evolution (mine) → skill → usage → reflection (clean) → archive
                ↑                                       ↓
                └──── self-evolution loop (weekly cron) ────┘
```

Three operations, one pipeline:

| Operation | Script | What it does |
|-----------|--------|-------------|
| **Scan** | `scripts/reflection/scan.py` | Weekly health check: memory, zombies, kanban |
| **Consolidate** | `scripts/reflection/consolidate.py` | Memory dedup: merge, compress, backup |
| **Evolve** | `scripts/reflection/evolve.py` | Auto-maintenance: archive zombies, check crons |

#### Scan (`scripts/reflection/scan.py`)

Weekly health scan that measures:

| Metric | Source | Threshold |
|--------|--------|-----------|
| Memory water level | `MEMORY.md` / `USER.md` file sizes | >80% of 2.2KB / 1.4KB limit |
| Zombie skills | Skill directories modified >60 days ago | Exclude stable-use categories |
| Kanban blockers | Kanban DB task ages | >48h in running/blocked |
| Session activity | SessionDB count in 7-day window | >200 or <10 |

Output: `~/.hermes/reflection/scan-report.json` with all metrics.

```bash
python3 scripts/reflection/scan.py --days 7
```

#### Consolidate (`scripts/reflection/consolidate.py`)

Memory deduplication — merges duplicate entries, removes exact repeats, compresses similar facts.

```bash
# Analyze current state (read-only)
python3 scripts/reflection/consolidate.py --analyze

# Remove exact duplicates (safe, with backup)
python3 scripts/reflection/consolidate.py --auto-apply

# Rollback if needed
python3 scripts/reflection/consolidate.py --rollback ~/.hermes/backups/phase2-<timestamp>/
```

Features:
- Full backup before any changes
- Rollback script generated with each backup
- Similar pair detection (≥85% similarity) for manual review

#### Evolve (`scripts/reflection/evolve.py`)

Auto-maintenance based on scan results:

```bash
# Show all actionable items
python3 scripts/reflection/evolve.py --report

# Dry-run: list zombies that could be archived
python3 scripts/reflection/evolve.py --archive-zombies

# Actually archive them
python3 scripts/reflection/evolve.py --archive-zombies --apply

# Check cron health
python3 scripts/reflection/evolve.py --check-crons
```

### Cron Integration

The Reflection system runs together with Evolution in a single weekly cron:

```yaml
Name: unified-weekly-maintenance
Schedule: 0 3 * * 0 (Sunday 3:00 AM)
Flow:
  1. Run scripts/reflection/scan.py (health metrics)
  2. Run evolution pipeline (case scan + re-cluster)
  3. Combine results → report only if actionable
```

A separate daily hook (`scripts/skill_evolution_hook.py`, cron at 12:00, no-agent) silently accumulates new cases.

### File Structure

```
~/.hermes/
├── scripts/
│   ├── mining/                  # Pattern discovery
│   │   ├── miner.py             # Case extraction + clustering
│   │   ├── forge.py             # LLM skill generation
│   │   ├── hook.py              # Incremental cron hook
│   │   ├── validator.py         # Validation pipeline
│   │   ├── signatures.py        # Tool-call signature system
│   │   └── ARCHITECTURE.md      # Mining system design doc
│   ├── reflection/              # Health maintenance
│   │   ├── scan.py              # Health scanner
│   │   ├── consolidate.py       # Memory dedup
│   │   └── evolve.py            # Auto-maintenance
│   ├── skill_evolution.py       # CLI orchestrator
│   └── skill_evolution_hook.py  # Daily incremental hook
│
├── reflection/
│   └── scan-report.json            # Latest scan output
│
├── agent/
│   ├── cases/                      # Evolution case DB
│   ├── candidates/                 # Skill candidates
│   └── .case_index.json            # Hook state tracker
│
└── skills/
    ├── hermes/skill-evolution/     # This skill
    └── .archive/                   # Archived zombie skills
```

### Memory Consolidation Archive

Backups of pre-consolidation memory live in `~/.hermes/backups/`. Rollback:
```bash
bash ~/.hermes/scripts/reflection/rollback.sh
```

### Key Design Decisions

1. **Silent by default** — Both the daily hook and weekly cron stay quiet unless there's something actionable. No noise.
2. **User approval gate** — No auto-deletion or auto-creation. Every action requires user confirmation.
3. **Reflection + Evolution as peers** — They share the same cron slot and report format but have orthogonal concerns: Reflection deletes/merges, Evolution creates.
