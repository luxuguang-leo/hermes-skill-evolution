# Hermes Skill Precipitator — Quick Example

## Prerequisites

- Hermes Agent installed and running
- Python 3.10+

## Full Demo

```bash
# 1. Scan recent sessions
python3 skill_precipitator.py scan --limit 100

# 2. See what was found
python3 skill_precipitator.py status

# 3. Cluster and forge
python3 skill_precipitator.py cluster
python3 skill_precipitator.py forge --min-cases 3

# 4. View candidates
python3 skill_precipitator.py report

# 5. Run unit tests
python3 skill_precipitator.py test
```

## Incremental Hook

```bash
# Single run
python3 skill_precipitator_hook.py

# Or register as cron
hermes cron create \
  --name skill-precipitator \
  --schedule "every 2h" \
  --script skill_precipitator_hook.py \
  --no-agent
```

## Expected Output

After scanning 500+ sessions, you should see output like:

```
📊 Summary:
  Total cases: ~100
  Avg tools/case: 36
  Top intents: search-find, install-setup, monitor-check
```

Then after forging:

```
🔨 Generated 6 skill candidates:
  📄 auto-model-install (8 cases)
  📄 auto-status-check (6 cases)
  📄 auto-search-find (5 cases)
  ...
```
