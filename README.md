# arXiv Digest

Track and summarize new AI/ML papers from arXiv using the official API + SQLite. Designed for use with [OpenClaw](https://github.com/openclaw/openclaw) but works standalone.

## What it does

- Pulls latest papers from 6 arXiv categories via official API (free, no key needed)
- Stores papers and metadata in a local SQLite database
- Supports focus profiles (LLM, agents, vision, etc.)
- Outputs structured JSON for LLM-powered digest generation
- Delivers daily digests to email subscribers

## Tracked Categories

| Code | Name |
|------|------|
| cs.AI | Artificial Intelligence |
| cs.LG | Machine Learning |
| cs.CL | Computation and Language (NLP/LLM) |
| cs.CV | Computer Vision |
| cs.MA | Multiagent Systems |
| stat.ML | Statistics - Machine Learning |

## Requirements

- Python 3.9+
- No external dependencies (uses standard library only)

## Quick Start

```bash
# Fetch latest papers from all categories
python3 arxiv_fetch.py

# Query today's papers, LLM focus
python3 arxiv_digest.py query 1 --focus llm

# List focus profiles
python3 arxiv_digest.py focus-profiles

# Quick stats
python3 arxiv_fetch.py stats 7
```

## Files

| File | Responsibility |
|------|---------------|
| `db.py` | Shared database schema and connection |
| `arxiv_fetch.py` | Pull arXiv API → store in SQLite |
| `arxiv_digest.py` | Query data, manage focus profiles and subscribers |

## Commands

### arxiv_fetch.py (data collection)

| Command | Description |
|---------|-------------|
| `fetch` | Pull latest papers → store in SQLite |
| `fetch --report-hour H` | Only output report when local hour == H |
| `stats [days]` | Quick stats |

### arxiv_digest.py (analysis & delivery)

| Command | Description |
|---------|-------------|
| `query [days] [--category X] [--focus Z]` | Query papers, output JSON |
| `save-summary [focus]` | Save summary text from stdin |
| `focus-profiles` | List all focus profiles |
| `add-focus <name> <json>` | Add a custom focus profile |
| `subscribers` | List all subscribers |
| `add-subscriber --email <email> [--name <name>] [--focus <focus>]` | Add subscriber |
| `remove-subscriber <email>` | Remove subscriber |
| `toggle-subscriber <email>` | Enable/disable subscriber |

## Focus Profiles

| Profile | Categories | Description |
|---------|-----------|-------------|
| `default` | All | No filter |
| `llm` | cs.CL, cs.AI | LLM/NLP focused |
| `agents` | cs.AI, cs.MA, cs.CL | AI Agents focused |
| `vision` | cs.CV | Computer Vision focused |

## Database

SQLite database at `data/arxiv.db` with 6 tables:

- **categories** — tracked arXiv categories (with enabled flag)
- **papers** — unique papers (title, authors, abstract, categories, URLs)
- **daily_entries** — fetch records linking papers to categories
- **summaries** — generated digest history
- **focus_profiles** — saved focus configurations
- **subscribers** — email subscribers with per-person focus

## Architecture

```
arxiv_fetch.py (1x/day, 9am)    arxiv_digest.py (1x/day, 10pm)
┌──────────────────┐            ┌──────────────────┐
│ arXiv API        │            │ query DB         │
│ 6 categories     │  SQLite    │ LLM draft        │
│ 50 papers each   │ ────────→  │ LLM review       │
└──────────────────┘  (db.py)   │ LLM final        │
                                │ save + email     │
                                └──────────────────┘
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARXIV_DIGEST_DB_PATH` | `./data/arxiv.db` | Override database location |

## License

MIT
