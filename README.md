# Hermes Skill Evolution

> Full lifecycle management for Hermes Agent skills — discover, forge, maintain, and retire.

**Zero modifications to Hermes core.** This is a self-contained add-on that reads SessionDB read-only
and writes to its own directories. Two subsystems work together:

| Subsystem | Direction | Goal | Action |
|-----------|-----------|------|--------|
| **Evolution** (mining) | Bottom-up | Discover new patterns → create skills | Extract cases, cluster, forge |
| **Reflection** (health) | Top-down | Clean up stale → maintain health | Scan metrics, consolidate, archive |

```
sessions → evolution (mine) → skill → usage → reflection (clean) → archive
                ↑                                       ↓
                └─── self-evolution loop (weekly cron) ────┘
```

---

## Subsystem 1: Evolution — Auto-Discover New Skills

Mines session history for repeated workflow patterns, clusters them, and generates SKILL.md candidates.

```
945 sessions → 155 cases → 14 skill candidates (real data run)
```

### Components

| Component | What it does | When |
|-----------|-------------|------|
| **Hook** (`scripts/evolution/hook.py`) | Incrementally scans new sessions, extracts cases, checks threshold | Cron daily 12:00, silent |
| **CLI** (`scripts/skill_evolution.py`) | Scan, cluster, forge, report, install | Manual |
| **Case DB** (`agent/cases/`) | Accumulated case files with tool signatures, user intent, n-gram patterns | Persistent |

### Pipeline

```
SessionDB → Case Miner → agent/cases/ → Multi-Factor Clustering
                                              ↓
                                       3+ similar cases?
                                              ↓
                                     Yes → Skill Forge
                                              ↓
                                     Skill Candidate
                                              ↓
                                     Review & Install
                                              ↓
                                     ~/.hermes/skills/
```

### Clustering Algorithm

Four weighted dimensions determine case similarity:

| Dimension | Weight | What it captures |
|-----------|--------|-----------------|
| Tool signature | 0.30 | 8 categories: SHELL, BROWSER, CODE, WEB, FILE, CRON, EMAIL, NOTIFY |
| User intent | 0.30 | install-setup, research, fix-debug, search-find, download-media, etc. |
| N-gram sequence | 0.20 | Bigram/trigram of tool categories (e.g. `SHELL>SHELL>FILE`) |
| Keyword similarity | 0.20 | Chinese word tokenization + Jaccard similarity |

---

## Subsystem 2: Reflection — Full Lifecycle

Three-operation pipeline that keeps Hermes running lean.

### Scan (`scripts/reflection_scan.py`)

Weekly health metrics:

| Metric | Source | Alert threshold |
|--------|--------|----------------|
| Memory water level | MEMORY.md / USER.md size | >80% of 2.2KB / 1.4KB limit |
| Zombie skills | SKILL.md modification age >60d | Excluding stable-use categories |
| Kanban blockers | Task stuck in running/blocked | >48 hours |
| Session activity | 7-day session count | >200 or <10 |

Output: `~/.hermes/reflection/scan-report.json`

### Consolidate

Memory deduplication — merges duplicate entries, removes exact repeats, compresses similar facts.
Manual execution with user review. Includes full backup + rollback capability.

### Evolve (Auto-Maintenance)

- Archive confirmed zombies → `~/.hermes/skills/.archive/`
- Set up automated weekly scan + report
- Integrate Evolution and Reflection into unified cron

---

## Cron Schedule

| Cron | Schedule | Mode | Purpose |
|------|----------|------|---------|
| `skill-evolution-hook` | Daily 12:00 | no-agent | Silently accumulate new cases |
| `unified-weekly-maintenance` | Sunday 03:00 | LLM agent | Full scan + analyze + report only if issues |

The unified cron runs both subsystems in sequence:
1. `reflection_scan.py --days 7` (health check)
2. `skill_evolution.py cluster` (re-cluster cases)
3. Combined analysis → silent if nothing actionable

---

## Quick Start

```bash
# 1. Clone
git clone git@github.com:luxuguang-leo/hermes-skill-evolution.git
cd hermes-skill-evolution

# 2. Install
python3 install.py

# 3. Run daily hook (incremental)
python3 scripts/skill_evolution_hook.py

# 4. Manual: full evolution pipeline
python3 scripts/skill_evolution.py scan --limit 500
python3 scripts/skill_evolution.py cluster --threshold 0.45
python3 scripts/skill_evolution.py forge --min-cases 3
python3 scripts/skill_evolution.py validate
python3 scripts/skill_evolution.py install <candidate-name>

# 5. Health scan
python3 scripts/reflection/scan.py --days 7

# 6. Status
python3 scripts/skill_evolution.py status

# 7. Consolidate: Memory dedup
python3 scripts/reflection/consolidate.py --analyze
python3 scripts/reflection/consolidate.py --auto-apply

# 8. Evolve: Auto-maintenance
python3 scripts/reflection/evolve.py --report
python3 scripts/reflection/evolve.py --archive-zombies --apply
```

---

## File Structure

```
~/.hermes/
├── scripts/
│   ├── mining/                    # Pattern discovery (was evolution/)
│   │   ├── miner.py               # Case extraction + clustering
│   │   ├── forge.py               # LLM skill generation
│   │   ├── hook.py                # Incremental cron hook
│   │   ├── validator.py           # Validation pipeline
│   │   ├── signatures.py          # Tool-call signature system
│   │   └── ARCHITECTURE.md        # Mining system design doc
│   ├── reflection/                # Health maintenance system
│   │   ├── scan.py                # Health scanner
│   │   ├── consolidate.py         # Memory dedup
│   │   └── evolve.py              # Auto-maintenance
│   ├── skill_evolution.py         # CLI orchestrator (mining + reflection)
│   └── skill_evolution_hook.py    # Daily incremental mining hook
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

---

## Design Principles

1. **Silent by default** — Daily hook and weekly cron only speak when actionable.
2. **User gates all actions** — No auto-delete, no auto-create. Every write requires confirmation.
3. **Zero core modifications** — No changes to `run_agent.py`, `hermes_state.py`, or gateway.
4. **Lossless archives** — Archived skills can always be restored from `.archive/`.
5. **Graceful degradation** — If pyatv, network, or external deps fail, the pipeline notes the error but continues.

---

## License

MIT — Open source at [github.com/luxuguang-leo/hermes-skill-evolution](https://github.com/luxuguang-leo/hermes-skill-evolution)
