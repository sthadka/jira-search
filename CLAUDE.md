# Claude Code Implementation Guide: Jira Search Mirror

## 🎯 Project Overview

Build a **local Jira search interface** that mirrors Jira issues into a fast, searchable SQLite database with a web UI. This solves the problem of Jira's slow, limited search capabilities by providing sub-1-second search with support for natural language, JQL, and regex queries.

**Core Value Proposition**: Transform 15-20% time waste in Jira navigation into productive search and bulk operations.

---

## 📋 Key Requirements Summary

### **Primary Features**
- **Jira Sync**: Full and incremental sync with Jira Data Center using Personal Access Tokens
- **Fast Search**: SQLite FTS5 with <1 second response times for 50k+ issues
- **Multiple Search Modes**: Natural language, JQL syntax, and regex patterns
- **Bulk Operations**: Select multiple results and open Jira bulk edit interface
- **Issue Preview**: Modal view with full issue details without leaving search interface
- **REST API**: For external tool integration

### **Technical Stack**
- **Backend**: Python with requests, sqlite3, Flask/FastAPI
- **Database**: SQLite with FTS5 for full-text search
- **Configuration**: YAML-based config files
- **Auth**: Personal Access Token stored in config.yaml
- **UI**: Single-page web interface (Google-like simplicity)

### **Performance Targets**
- **Search Response**: <1 second for datasets up to 100k issues
- **Type-ahead**: <100ms for autocomplete suggestions
- **Sync Operations**: Background processing, doesn't impact search
- **Memory Usage**: <512MB RAM under normal operations

---

## 🏗️ Implementation Strategy

### **Phase-Based Development**
Follow the 10-phase roadmap in `TODO.md` for iterative development:

1. **Phase 1**: Foundation (Jira connection, basic database)
2. **Phase 2**: Core sync engine with CLI commands
3. **Phase 3**: Basic web UI with search
4. **Phase 4**: Advanced search (JQL, regex)
5. **Phase 5**: Polish (type-ahead, issue preview)
6. **Phase 6**: Bulk operations
7. **Phase 7**: Enhanced sync management
8. **Phase 8**: Configuration management
9. **Phase 9**: REST API
10. **Phase 10**: Production readiness

### **Git Workflow**
- **Auto-commit** after each sub-phase using semantic commit messages
- Examples: `feat: add jira connection validation`, `fix: handle api rate limiting`

---

## 🔧 Technical Specifications

### **Database Schema (Denormalized for Search Performance)**
```sql
-- Core issues table optimized for search
CREATE TABLE issues (
    key TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    description TEXT,
    status INTEGER,  -- enum: 1=Open, 2=In Progress, 3=Done, etc.
    priority INTEGER,  -- enum: 1=Highest, 2=High, 3=Medium, etc.
    assignee TEXT,
    reporter TEXT,
    created DATETIME,
    updated DATETIME,
    comments TEXT,  -- All comments combined into single searchable field
    -- Custom fields from config.yaml
    custom_field_1 TEXT,
    custom_field_2 TEXT,
    -- ... more custom fields as configured
    raw_json TEXT  -- Store full Jira JSON for reference
);

-- FTS5 virtual table for fast search
CREATE VIRTUAL TABLE issues_fts USING fts5(
    key, summary, description, comments, assignee,
    content='issues'
);
```

### **Configuration Structure (config.yaml)**
```yaml
jira:
  url: "https://your-jira.company.com"
  username: "your-username"
  pat: "your-personal-access-token"
  
sync:
  project_key: "PROJ"  # Or use jql instead
  jql: "project = PROJ AND created >= -30d"  # Alternative to project_key
  rate_limit: 100  # requests per minute
  batch_size: 100  # issues per batch
  
custom_fields:
  - id: "customfield_10001"
    name: "Story Points"
    type: "number"
  - id: "customfield_10002" 
    name: "Epic Link"
    type: "text"

search:
  max_results: 1000
  timeout_seconds: 5
```

### **CLI Interface**
```bash
# Setup and validation
python -m jira_search init-config          # Generate config.yaml.example
python -m jira_search test-connection      # Validate Jira connection
python -m jira_search validate-config      # Check config file

# Sync operations
python -m jira_search sync --project KEY   # Full sync by project
python -m jira_search sync --jql "..."     # Full sync by JQL query  
python -m jira_search sync --incremental   # Incremental sync
python -m jira_search sync --full          # Force full re-sync
python -m jira_search sync --dry-run       # Show what would be synced

# Status and management
python -m jira_search status               # Show sync status and stats
python -m jira_search serve                # Start web server (default: port 8080)
```

---

## 🔍 Search Implementation Details

### **Search Modes**
1. **Natural Language**: Use FTS5 MATCH queries with ranking
2. **JQL**: Parse and convert to SQLite WHERE clauses
3. **Regex**: Use SQLite REGEXP operator with timeout protection

### **JQL Support (Priority Fields)**
```python
# Map JQL fields to database columns
JQL_FIELD_MAPPING = {
    'project': 'project_key',
    'assignee': 'assignee', 
    'status': 'status',
    'priority': 'priority',
    'created': 'created',
    'updated': 'updated',
    'summary': 'summary',
    'description': 'description'
}

# Support JQL operators: =, !=, IN, AND, OR, >, <, >=, <=
# Example: "assignee = currentUser() AND status IN ('In Progress', 'Open')"
```

### **API Endpoints**
```python
# Core search API
GET /api/search?q=term&mode=natural&limit=100&offset=0
GET /api/suggest?q=partial  # Type-ahead suggestions
GET /api/issues/{key}       # Issue details

# Response format
{
    "results": [...],
    "total": 1234,
    "query_time_ms": 245,
    "mode": "natural"
}
```

---

## 🎨 UI/UX Requirements

### **Single-Page Interface**
- **Header**: Simple search box with mode toggle (Natural Language | JQL | Regex)
- **Quick Filters**: "My Issues", "Open Issues", "Recent" as clickable chips
- **Results**: Card layout with issue key, summary, status, assignee, updated date
- **Bulk Actions**: Checkbox selection with "Bulk Edit in Jira" button
- **Issue Preview**: Modal with full details, comments, custom fields

### **Keyboard Navigation**
- `Ctrl+K`: Focus search box
- `↑/↓`: Navigate results and suggestions
- `Enter`: Open issue preview
- `Esc`: Close modals
- `Ctrl+A`: Select all results

---

## ⚡ Performance Optimizations

### **Database Design**
- **Denormalized schema** - combine comments into single field
- **Integer enums** for status/priority instead of strings
- **FTS5 indexes** on all searchable text fields
- **Regular indexes** on frequently filtered fields (assignee, status, updated)

### **Sync Efficiency**
- **Incremental sync** using `updated >= last_sync_time`
- **Batch processing** with configurable batch sizes
- **Rate limiting** with exponential backoff
- **Resume capability** for interrupted syncs

### **Search Optimization**
- **Query timeout**: 5 seconds max for regex queries
- **Result limiting**: 1000 results max with pagination
- **Caching**: Type-ahead suggestions cached for 5 minutes
- **Concurrent handling**: SQLite WAL mode for concurrent reads

---

## 🛡️ Security & Error Handling

### **Security**
- Store PAT in config.yaml (no special encryption needed for local use)
- Validate all user inputs (search queries, config values)
- Use HTTPS for all Jira API calls
- No sensitive data in error messages or logs

### **Error Handling**
- **Jira API errors**: Retry with exponential backoff, graceful degradation
- **Database errors**: Clear error messages, suggest solutions
- **Search errors**: Validate regex patterns, handle timeouts
- **Sync errors**: Resume from last successful batch, detailed logging

### **User-Friendly Error Messages**
```python
# Examples of good error messages
"Connection failed: Unable to connect to Jira at {url}. Check your network connection and server URL."
"Authentication failed: Invalid Personal Access Token. Please verify your credentials in config.yaml."
"Sync incomplete: Network error occurred. Last successful sync: {timestamp}. Run sync command again to continue."
"Search timeout: Complex regex pattern took too long. Try a simpler pattern or use natural language search."
```

---

## 📊 Logging & Monitoring

### **Essential Logging**
```python
# Log levels and key events
logger.info("Sync started", extra={"type": "full", "query": "project = PROJ"})
logger.info("Sync completed", extra={"duration": 120, "issues_processed": 1500, "issues_updated": 50})
logger.warning("Rate limit reached", extra={"retry_after": 60})
logger.error("Database error", extra={"error": str(e)}, exc_info=True)

# Performance logging
logger.debug("Search query", extra={"query": query, "mode": mode, "result_count": len(results), "query_time_ms": elapsed})
```

---

## 🧪 Testing Strategy

### **Test Coverage Priorities**
1. **Jira API client** - connection, authentication, pagination
2. **Database operations** - sync, search, FTS5 queries  
3. **Search functionality** - natural language, JQL parsing, regex
4. **CLI commands** - all sync and management operations
5. **Error handling** - network failures, invalid configs, malformed data

### **Test Data**
- Use mock Jira API responses for unit tests
- Include edge cases: empty fields, special characters, large comments
- Test with realistic dataset sizes (1k, 10k, 50k issues)

---

## 🚀 Implementation Priority

### **Start with Phase 1** from TODO.md:
1. **Project structure** with proper Python packaging
2. **Config management** with YAML loading and validation
3. **Jira API client** with PAT authentication
4. **Basic database** with core schema and migrations
5. **CLI framework** with connection testing

### **Success Criteria for Phase 1**:
✅ `python -m jira_search test-connection` successfully connects to Jira
✅ Database creates and initializes properly  
✅ Config validation catches common errors
✅ All code follows Python best practices with proper error handling

### **Validation Commands**:
```bash
# Test each component works
python -m jira_search init-config
python -m jira_search validate-config  
python -m jira_search test-connection
python -m jira_search sync --dry-run --project TEST
```

---

## 📚 Key Files Reference

- **`requirements/prd.md`**: Product requirements and success metrics
- **`requirements/functional_spec.md`**: Detailed user stories and acceptance criteria  
- **`requirements/nfr.md`**: Performance, security, and technical requirements
- **`requirements/TODO.md`**: Complete phase-by-phase implementation roadmap

**Follow the TODO.md phases sequentially** - each phase builds on the previous and has clear validation criteria. This ensures you can course-correct based on real performance and usability data.

---

*Ready to build a tool that genuinely improves how teams work with Jira data! 🎯*