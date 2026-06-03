# gcp-cost-analyzer

Autonomous GCP cost analysis tool powered by Gemini. Analyzes billing data, detects idle resources, and generates actionable Markdown reports with AI-driven recommendations.

## Features

- **Cost breakdown** — top services by spend, period-over-period delta
- **Idle resource detection** — unattached disks, unused snapshots, underutilized GKE nodes
- **AI recommendations** — Gemini analyzes patterns and suggests optimizations in natural language
- **Markdown reports** — saved locally or committed via GitHub Actions
- **Scheduled runs** — GitHub Actions workflow for daily/weekly analysis

## Requirements

- Python 3.11+
- GCP Service Account with roles:
  - `roles/billing.viewer`
  - `roles/compute.viewer`
  - `roles/container.viewer`
  - `roles/monitoring.viewer`
- Gemini API key (optional — works without it, skips AI recommendations)

## Setup

```bash
git clone https://github.com/n0rm4l-me/gcp-cost-analyzer
cd gcp-cost-analyzer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables:

```bash
export GCP_BILLING_ACCOUNT_ID="XXXXXX-XXXXXX-XXXXXX"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
export GEMINI_API_KEY="your-key-here"          # optional
export GCP_PROJECT_ID="your-project-id"        # optional, for resource analysis
```

## Usage

```bash
# Analyze last 30 days, save report to reports/
python -m src.main

# Custom period
python -m src.main --days 7

# Specific project
python -m src.main --project your-project-id --days 30

# Skip Gemini recommendations
python -m src.main --no-ai
```

## Output

Reports are saved to `reports/YYYY-MM-DD.md`:

```
# GCP Cost Analysis — 2026-06-01

## Summary
Total spend: $12,450.32 (+8.3% vs previous period)

## Top Services
| Service | Cost | Delta |
|---------|------|-------|
| Kubernetes Engine | $4,230 | +12% |
...

## Idle Resources
- 3 unattached persistent disks (~$45/mo)
- 2 GKE node pools underutilized (<20% CPU for 7d)
...

## AI Recommendations
*Powered by Gemini*
> Your Kubernetes Engine costs increased 12% — primarily driven by...
```

## GitHub Actions

Runs every Monday at 09:00 UTC, commits report to `reports/`:

```yaml
# .github/workflows/analyze.yml
# Requires secrets: GCP_SA_KEY, GCP_BILLING_ACCOUNT_ID, GEMINI_API_KEY
```
