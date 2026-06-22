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

## Subsystem 2: Reflection — System Health Maintenance

Three-phase health system that keeps Hermes running lean.

### Phase 1: Scan (`scripts/reflection_scan.py`)

Weekly health metrics:

| Metric | Source | Alert threshold |
|--------|--------|----------------|
| Memory water level | MEMORY.md / USER.md size | >80% of 2.2KB / 1.4KB limit |
| Zombie skills | SKILL.md modification age >60d | Excluding stable-use categories |
| Kanban blockers | Task stuck in running/blocked | >48 hours |
| Session activity | 7-day session count | >200 or <10 |

Output: `~/.hermes/reflection/scan-report.json`

### Phase 2: Consolidate

Memory deduplication — merges duplicate entries, removes exact repeats, compresses similar facts.
Manual execution with user review. Includes full backup + rollback capability.

### Phase 3: Evolve (Auto-Maintenance)

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
python3 scripts/reflection_scan.py --days 7

# 6. Status
python3 scripts/skill_evolution.py status

# 7. Phase 2: Memory consolidation
python3 scripts/phase2_consolidate.py --analyze
python3 scripts/phase2_consolidate.py --auto-apply

# 8. Phase 3: Auto-maintenance
python3 scripts/phase3_evolve.py --report
python3 scripts/phase3_evolve.py --archive-zombies --apply
```

---

## File Structure

```
~/.hermes/
├── scripts/
│   ├── evolution/                 # Evolution core modules
│   │   ├── miner.py               # Case extraction + clustering
│   │   ├── forge.py               # LLM skill generation
│   │   ├── validator.py           # Validation pipeline
│   │   ├── hook.py                # Incremental cron hook
│   │   ├── signatures.py          # Tool-call signature system
│   │   ├── presenter.py           # Report formatting
│   │   └── ARCHITECTURE.md        # Design document
│   ├── reflection/                # Reflection support (TODO)
│   │   └── rollback.sh            # Memory consolidation rollback
│   ├── reflection_scan.py         # Phase 1: health scanner
│   ├── phase2_consolidate.py      # Phase 2: memory dedup
│   ├── phase3_evolve.py           # Phase 3: auto-maintenance
│   ├── skill_evolution.py         # Evolution CLI orchestrator
│   └── skill_evolution_hook.py    # Daily incremental hook
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
