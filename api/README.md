# Jira Search Mirror API

A comprehensive REST API for the Jira Search Mirror application, providing fast local search capabilities for Jira issues.

## Overview

The Jira Search Mirror API provides programmatic access to search and retrieve Jira issues from a locally mirrored database. It supports multiple search modes, type-ahead suggestions, and comprehensive issue details.

### Key Features

- **Fast Search**: Sub-1-second response times with FTS5 full-text search
- **Multiple Search Modes**: Natural language, JQL syntax, and regex patterns
- **Type-ahead Suggestions**: Intelligent autocomplete for all search modes
- **API Authentication**: Optional API key authentication with rate limiting
- **Comprehensive Documentation**: OpenAPI 3.0 specification with interactive docs

## Quick Start

### 1. Start the Server

```bash
# Start the Jira Search Mirror server
python -m jira_search serve

# Server will be available at http://localhost:8080
```

### 2. Basic API Usage

```bash
# Search for issues with natural language
curl "http://localhost:8080/api/v1/search?q=security%20vulnerability&mode=natural&limit=5"

# Get issue details
curl "http://localhost:8080/api/v1/issues/ROX-12345"

# Get search suggestions
curl "http://localhost:8080/api/v1/suggest?q=ROX-&mode=natural&limit=5"
```

### 3. With API Key Authentication

```bash
# Search with API key for higher rate limits
curl -H "X-API-Key: your-api-key" \
     "http://localhost:8080/api/v1/search?q=project%20=%20ROX&mode=jql"

# Get API key information
curl -H "X-API-Key: your-api-key" \
     "http://localhost:8080/api/v1/auth/info"
```

## API Documentation

### Interactive Documentation

Visit the interactive API documentation in your browser:

- **Swagger UI**: http://localhost:8080/api/v1/docs/ui
- **OpenAPI Spec**: http://localhost:8080/api/v1/docs

### API Versioning

The API uses versioning to ensure compatibility:

- **Current Version**: v1
- **Base URL**: `/api/v1/`
- **Backward Compatibility**: Legacy endpoints at `/api/` redirect to v1

## Authentication

### API Keys

API keys provide higher rate limits and access to authenticated endpoints:

```http
X-API-Key: your-api-key-here
```

**Rate Limits:**
- Anonymous: 30 requests/minute
- Authenticated: 60-300 requests/minute (depends on key tier)

### Development Keys

For testing purposes, you can use these development API keys:

- `dev-key-12345`: Development key (120 requests/minute)
- `prod-key-67890`: Production key (300 requests/minute)

## Core Endpoints

### Search Issues

Search for issues using natural language, JQL, or regex:

```http
GET /api/v1/search?q={query}&mode={mode}&limit={limit}&offset={offset}
```

**Parameters:**
- `q`: Search query (required)
- `mode`: `natural` (default), `jql`, or `regex`
- `limit`: Max results (default: 100, max: 1000)
- `offset`: Pagination offset (default: 0)

**Example Response:**
```json
{
  "results": [
    {
      "key": "ROX-12345",
      "summary": "Fix security vulnerability in authentication",
      "status_name": "Open",
      "priority_name": "High",
      "assignee_display_name": "John Doe",
      "project_key": "ROX",
      "created": "2025-01-15T10:30:00.000+0000",
      "updated": "2025-01-20T14:22:00.000+0000"
    }
  ],
  "total": 1,
  "query": "security vulnerability",
  "mode": "natural",
  "query_time_ms": 245
}
```

### Get Issue Details

Retrieve complete information for a specific issue:

```http
GET /api/v1/issues/{issueKey}
```

**Example:**
```bash
curl "http://localhost:8080/api/v1/issues/ROX-12345"
```

### Search Suggestions

Get intelligent type-ahead suggestions:

```http
GET /api/v1/suggest?q={partial_query}&mode={mode}&limit={limit}
```

**Example:**
```bash
curl "http://localhost:8080/api/v1/suggest?q=ROX-&mode=natural&limit=5"
```

### Query Validation

Validate JQL or regex queries before execution:

```http
GET /api/v1/validate?q={query}&mode={mode}
```

**Example:**
```bash
curl "http://localhost:8080/api/v1/validate?q=project%20=%20ROX&mode=jql"
```

### System Status

Get system health and statistics:

```http
GET /api/v1/status
```

**Example Response:**
```json
{
  "status": "healthy",
  "database": {
    "total_issues": 11514,
    "last_sync": "2025-08-06T12:40:38.329316",
    "database_size_mb": 129.1
  }
}
```

## Search Modes

### Natural Language Search

Default mode using FTS5 full-text search with intelligent ranking:

```bash
curl "http://localhost:8080/api/v1/search?q=authentication%20bug&mode=natural"
```

### JQL (Jira Query Language)

Use Jira's native query language for precise filtering:

```bash
curl "http://localhost:8080/api/v1/search?q=project%20=%20ROX%20AND%20status%20=%20Open&mode=jql"
```

**Supported JQL Fields:**
- `project`, `assignee`, `status`, `priority`
- `created`, `updated`, `summary`, `description`
- `labels`, `components`, `type`, `key`
- Custom fields: `team`, `work_type`, `product_manager`

### Regex Search

Pattern matching using regular expressions:

```bash
curl "http://localhost:8080/api/v1/search?q=ROX-\\d{5}&mode=regex"
```

## Client Libraries

### Python

```python
from jira_search_client import JiraSearchClient

client = JiraSearchClient(api_key="your-api-key")
results = client.search("security vulnerability", mode="natural", limit=10)

for issue in results['results']:
    print(f"{issue['key']}: {issue['summary']}")
```

See: [`examples/python_client.py`](examples/python_client.py)

### JavaScript

```javascript
const client = new JiraSearchClient({ apiKey: 'your-api-key' });

const results = await client.search('security vulnerability', { 
  mode: 'natural', 
  limit: 10 
});

results.results.forEach(issue => {
  console.log(`${issue.key}: ${issue.summary}`);
});
```

See: [`examples/javascript_client.js`](examples/javascript_client.js)

### curl/Shell

Complete examples with error handling and rate limiting:

```bash
# Run the interactive examples
./examples/curl_examples.sh
```

See: [`examples/curl_examples.sh`](examples/curl_examples.sh)

## Error Handling

### HTTP Status Codes

- `200 OK`: Successful request
- `400 Bad Request`: Invalid parameters
- `401 Unauthorized`: Invalid or missing API key
- `404 Not Found`: Resource not found
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Server error

### Error Response Format

```json
{
  "error": "Rate limit exceeded",
  "message": "Maximum 60 requests per minute allowed",
  "retry_after": 45
}
```

### Rate Limiting Headers

All responses include rate limiting information:

```http
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1641234567
```

## Development

### Running Examples

1. **Start the server:**
   ```bash
   python -m jira_search serve
   ```

2. **Run Python example:**
   ```bash
   cd api/examples
   python python_client.py
   ```

3. **Run JavaScript example:**
   ```bash
   cd api/examples
   node javascript_client.js
   ```

4. **Run curl examples:**
   ```bash
   cd api/examples
   ./curl_examples.sh
   ```

### Testing API Endpoints

Use the interactive documentation for testing:

1. Open http://localhost:8080/api/v1/docs/ui
2. Click "Try it out" on any endpoint
3. Enter parameters and execute requests
4. View responses and examples

## Production Deployment

### Security Considerations

1. **API Keys**: Use strong, unique API keys in production
2. **HTTPS**: Always use HTTPS in production environments
3. **Rate Limiting**: Monitor and adjust rate limits based on usage
4. **Monitoring**: Set up monitoring for API usage and errors

### Configuration

API keys and rate limits can be configured in the application:

```python
# In production, load from secure configuration
api_keys = {
    'prod-key-secure-123': {
        'name': 'Production Application',
        'rate_limit': 300,
        'enabled': True
    }
}
```

## Support

- **Documentation**: http://localhost:8080/api/v1/docs/ui
- **API Reference**: http://localhost:8080/api/v1/docs  
- **Examples**: See `examples/` directory
- **Issues**: Report issues in the project repository

## License

This API documentation and examples are provided under the same license as the Jira Search Mirror project.