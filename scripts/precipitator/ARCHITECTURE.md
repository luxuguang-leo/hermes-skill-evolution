# Skill Precipitator — Architecture Design

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

### 4. Presenter (`presenter.py`)

**Input**: Validated skill candidates
**Output**: User-facing report

- Generate report with sample data, use cases, expected behavior
- Support one-click skill creation

## Storage Structure

```
~/.hermes/
├── scripts/
│   ├── precipitator/           # Core modules
│   │   ├── ARCHITECTURE.md     # This document
│   │   ├── miner.py            # Case extraction + clustering
│   │   ├── forge.py            # LLM skill generation
│   │   ├── validator.py        # Validation pipeline
│   │   └── presenter.py        # User presentation
│   └── skill_precipitator.py   # CLI entry (orchestrator)
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
