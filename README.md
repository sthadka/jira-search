# Jira Search

Fast local search for Jira issues with sub-1-second response times.

## Why

* Search through Jira summary, description and comments through full text
* Learn Claude Code usage by building a useful project

## Quick Start

```bash
# Install
pip install -e .

# Configure
python -m jira_search init-config
# Edit config.yaml with your Jira details

# Sync issues
python -m jira_search sync --project YOUR_PROJECT

# Start web interface
python -m jira_search serve
```

Open http://localhost:8080 to search your issues.

## Features

- **Fast Search**: SQLite FTS5 with sub-1-second response times
- **Multiple Modes**: Natural language, JQL syntax, and regex patterns
- **Bulk Operations**: Select multiple issues and open in Jira
- **REST API**: Full API for external tool integration
- **Issue Preview**: View full issue details without leaving search

## CLI Commands

```bash
# Setup
python -m jira_search init-config      # Generate config template
python -m jira_search test-connection  # Validate Jira connection

# Sync operations
python -m jira_search sync --project KEY    # Sync by project
python -m jira_search sync --jql "..."      # Sync by JQL query
python -m jira_search sync --incremental    # Incremental sync

# Server
python -m jira_search serve            # Start web server (port 8080)
python -m jira_search status           # Show sync status
```

## API Usage

```bash
# Search issues
curl "http://localhost:8080/api/v1/search?q=security&mode=natural"

# Get issue details
curl "http://localhost:8080/api/v1/issues/PROJ-123"

# API documentation
open http://localhost:8080/api/v1/docs/ui
```

## Configuration

Edit `config.yaml`:

```yaml
jira:
  url: "https://your-jira.company.com"
  username: "your-username"
  pat: "your-personal-access-token"

sync:
  project_key: "PROJ"  # Or use jql instead
  rate_limit: 100
```

## Container Deployment

### Run with Podman/Docker

Build and run the application in a container:

```bash
# Build container image
podman build -t jira-search:local .

# Run with existing database and configuration
podman run --rm \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/jira_search.db:/app/data/jira_search.db:ro \
  -p 8080:8080 \
  -e JIRA_PAT=your-personal-access-token \
  --name jira-search-test \
  jira-search:local
```

The container runs with Gunicorn WSGI server (4 workers) for production-grade performance.

### Kubernetes Deployment

Deploy to Kubernetes using the included Helm chart:

```bash
# Install with Helm
helm install jira-search ./charts/jira-search \
  --set secrets.jira_pat=your-personal-access-token \
  --set config.jira_url=https://your-jira.company.com \
  --set config.jira_username=your-username
```

See `charts/jira-search/values.yaml` for full configuration options including:
- Persistent volume configuration
- Initial sync job settings  
- Incremental sync schedule (default: every 15 minutes)
- Resource limits and security contexts

## Requirements

- Python 3.8+
- Jira Data Center with Personal Access Token
- SQLite 3.35+ (for FTS5 support)
- Podman/Docker (for container deployment)
- Kubernetes + Helm (for production deployment)
