"""Web interface for Jira Search."""

import time
import logging
import sqlite3
import os
import yaml
from typing import List, Dict, Any
from flask import Flask, render_template, request, jsonify
from jira_search.config import Config
from jira_search.database import Database, DatabaseError
from jira_search.search import AdvancedSearch, SearchError, JQLError, RegexError
from jira_search.api_auth import (
    apply_rate_limit,
    optional_api_key,
    require_api_key,
    add_api_info_headers,
)

logger = logging.getLogger(__name__)


def _get_issue_key_suggestions(
    db: Database, query: str, limit: int = 3
) -> List[Dict[str, Any]]:
    """Get suggestions for issue keys matching the query."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT key, summary FROM issues
                WHERE key LIKE ?
                ORDER BY updated DESC
                LIMIT ?
            """,
                (f"{query.upper()}%", limit),
            )

            return [
                {
                    "type": "issue_key",
                    "value": row[0],
                    "label": f"{row[0]} - {row[1][:60]}{'...' if len(row[1]) > 60 else ''}",
                    "icon": "🎫",
                }
                for row in cursor.fetchall()
            ]
    except Exception:
        return []


def _get_assignee_suggestions(
    db: Database, query: str, limit: int = 2
) -> List[Dict[str, Any]]:
    """Get suggestions for assignees matching the query."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT assignee_display_name, COUNT(*) as issue_count
                FROM issues
                WHERE assignee_display_name LIKE ? AND assignee_display_name IS NOT NULL
                GROUP BY assignee_display_name
                ORDER BY issue_count DESC
                LIMIT ?
            """,
                (f"%{query}%", limit),
            )

            return [
                {
                    "type": "assignee",
                    "value": row[0],
                    "label": f"👤 {row[0]} ({row[1]} issues)",
                    "icon": "👤",
                }
                for row in cursor.fetchall()
            ]
    except Exception:
        return []


def _get_team_suggestions(
    db: Database, query: str, limit: int = 2
) -> List[Dict[str, Any]]:
    """Get suggestions for teams matching the query."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT custom_12313240, COUNT(*) as issue_count
                FROM issues
                WHERE custom_12313240 LIKE ? AND custom_12313240 IS NOT NULL
                GROUP BY custom_12313240
                ORDER BY issue_count DESC
                LIMIT ?
            """,
                (f"%{query}%", limit),
            )

            return [
                {
                    "type": "team",
                    "value": row[0],
                    "label": f"👥 {row[0]} ({row[1]} issues)",
                    "icon": "👥",
                }
                for row in cursor.fetchall()
            ]
    except Exception:
        return []


def _get_summary_suggestions(
    db: Database, query: str, limit: int = 3
) -> List[Dict[str, Any]]:
    """Get suggestions from issue summaries matching the query."""
    try:
        results, _ = db.search_issues(query, limit=limit)
        return [
            {
                "type": "summary",
                "value": result["key"],
                "label": f"📄 {result['key']}: {result['summary'][:60]}"
                + ("..." if len(result["summary"]) > 60 else ""),
                "icon": "📄",
            }
            for result in results
        ]
    except Exception:
        return []


def _get_jql_suggestions(
    db: Database, query: str, limit: int = 8
) -> List[Dict[str, Any]]:
    """Get JQL-specific suggestions."""
    suggestions = []
    query_lower = query.lower()

    # Field suggestions
    jql_fields = [
        ("project", "📁", "Project key"),
        ("assignee", "👤", "Assignee name"),
        ("status", "🏷️", "Issue status"),
        ("priority", "⚡", "Issue priority"),
        ("team", "👥", "Team name"),
        ("work_type", "🔧", "Work type"),
        ("created", "📅", "Created date"),
        ("updated", "📅", "Updated date"),
    ]

    for field, icon, description in jql_fields:
        if field.startswith(query_lower) or query_lower in field:
            suggestions.append(
                {
                    "type": "jql_field",
                    "value": f"{field} = ",
                    "label": f"{icon} {field} = (${description})",
                    "icon": icon,
                }
            )

    # Common JQL patterns
    if "project" in query_lower:
        suggestions.append(
            {
                "type": "jql_example",
                "value": "project = ROX",
                "label": "📁 project = ROX",
                "icon": "📁",
            }
        )

    if "team" in query_lower:
        # Get actual team names
        try:
            with sqlite3.connect(db.db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT custom_12313240
                    FROM issues
                    WHERE custom_12313240 IS NOT NULL
                    LIMIT 3
                """
                )
                for row in cursor.fetchall():
                    suggestions.append(
                        {
                            "type": "jql_value",
                            "value": f'team = "{row[0]}"',
                            "label": f'👥 team = "{row[0]}"',
                            "icon": "👥",
                        }
                    )
        except Exception:
            pass

    return suggestions[:limit]


def _get_regex_suggestions(
    db: Database, query: str, limit: int = 8
) -> List[Dict[str, Any]]:
    """Get regex pattern suggestions."""
    suggestions = []

    # Common regex patterns
    patterns = [
        ("ROX-\\d+", "🎫", "Match any ROX issue number"),
        ("ROX-\\d{5}", "🎫", "Match 5-digit ROX issues"),
        ("(bug|fix)", "🐛", "Match bug or fix keywords"),
        ("^Fix.*", "🔧", 'Issues starting with "Fix"'),
        ("(critical|blocker)", "🚨", "High priority issues"),
        ("automation", "🤖", "Automation-related issues"),
    ]

    query_lower = query.lower()
    for pattern, icon, description in patterns:
        if query in pattern or any(
            word in pattern.lower() for word in query_lower.split()
        ):
            suggestions.append(
                {
                    "type": "regex_pattern",
                    "value": pattern,
                    "label": f"{icon} {pattern} - {description}",
                    "icon": icon,
                }
            )

    # If query looks like start of a pattern, suggest completions
    if query.startswith("ROX"):
        if "\\d" not in query:
            suggestions.append(
                {
                    "type": "regex_completion",
                    "value": "ROX-\\d+",
                    "label": "🎫 ROX-\\d+ - Match any ROX issue",
                    "icon": "🎫",
                }
            )

    return suggestions[:limit]


def create_app(config: Config) -> Flask:
    """Create and configure Flask application.

    Args:
        config: Configuration object

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "jira-search-secret-key"  # For session management

    # Initialize database connection and search engine
    db = Database(config)
    search_engine = AdvancedSearch(db, timeout_seconds=config.search_timeout_seconds)

    @app.route("/")
    def index():
        """Main search interface."""
        try:
            # Get database statistics for display
            stats = db.get_statistics()
            return render_template("index.html", stats=stats)
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return render_template("error.html", error="Database not available"), 500

    @app.route("/api/v1/search")
    @app.route("/api/search")  # Backward compatibility
    @apply_rate_limit
    @optional_api_key
    def api_search():
        """Search API endpoint.

        Query parameters:
        - q: Search query (required)
        - limit: Maximum results (default: 100, max: 1000)
        - offset: Pagination offset (default: 0)
        - mode: Search mode (default: 'natural')

        Returns:
        JSON response with search results
        """
        start_time = time.time()

        # Get query parameters
        query = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 100)), config.search_max_results)
        offset = int(request.args.get("offset", 0))
        mode = request.args.get("mode", "natural")

        if not query:
            return (
                jsonify(
                    {
                        "error": 'Query parameter "q" is required',
                        "results": [],
                        "total": 0,
                        "query_time_ms": 0,
                    }
                ),
                400,
            )

        try:
            # Perform search using advanced search engine
            results, total = search_engine.search(
                query, mode, limit=limit, offset=offset
            )

            # Calculate query time
            query_time_ms = int((time.time() - start_time) * 1000)

            # Format results for JSON response
            formatted_results = []
            for result in results:
                formatted_result = {
                    "key": result["key"],
                    "summary": result["summary"],
                    "description": result.get("description", ""),
                    "status_name": result["status_name"],
                    "priority_name": result["priority_name"],
                    "assignee_display_name": result["assignee_display_name"],
                    "reporter_display_name": result["reporter_display_name"],
                    "created": result["created"],
                    "updated": result["updated"],
                    "project_key": result["project_key"],
                    "project_name": result["project_name"],
                    "issue_type": result["issue_type"],
                    "labels": result.get("labels", ""),
                    "components": result.get("components", ""),
                    "custom_fields": {
                        "px_impact_score": result.get("custom_12322244"),
                        "product_manager": result.get("custom_12316752"),
                        "work_type": result.get("custom_12320040"),
                        "team": result.get("custom_12313240"),
                    },
                }
                formatted_results.append(formatted_result)

            return jsonify(
                {
                    "results": formatted_results,
                    "total": total,
                    "query": query,
                    "mode": mode,
                    "limit": limit,
                    "offset": offset,
                    "query_time_ms": query_time_ms,
                }
            )

        except (SearchError, JQLError, RegexError) as e:
            logger.error(f"Search error: {e}")
            return (
                jsonify(
                    {
                        "error": str(e),
                        "results": [],
                        "total": 0,
                        "query_time_ms": int((time.time() - start_time) * 1000),
                    }
                ),
                400,
            )
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return (
                jsonify(
                    {
                        "error": f"Database error: {str(e)}",
                        "results": [],
                        "total": 0,
                        "query_time_ms": int((time.time() - start_time) * 1000),
                    }
                ),
                500,
            )
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return (
                jsonify(
                    {
                        "error": "Internal server error",
                        "results": [],
                        "total": 0,
                        "query_time_ms": int((time.time() - start_time) * 1000),
                    }
                ),
                500,
            )

    @app.route("/api/v1/suggest")
    @app.route("/api/suggest")  # Backward compatibility
    @apply_rate_limit
    @optional_api_key
    def api_suggest():
        """Type-ahead suggestions API endpoint.

        Query parameters:
        - q: Partial query (required)
        - mode: Search mode (default: 'natural')
        - limit: Maximum suggestions (default: 8)

        Returns:
        JSON response with intelligent suggestions
        """
        query = request.args.get("q", "").strip()
        mode = request.args.get("mode", "natural")
        limit = int(request.args.get("limit", 8))

        if not query or len(query) < 2:
            return jsonify({"suggestions": []})

        try:
            suggestions = []

            if mode == "natural":
                # For natural language, provide mixed suggestions
                suggestions.extend(_get_issue_key_suggestions(db, query, limit=3))
                suggestions.extend(_get_assignee_suggestions(db, query, limit=2))
                suggestions.extend(_get_team_suggestions(db, query, limit=2))
                suggestions.extend(_get_summary_suggestions(db, query, limit=3))

            elif mode == "jql":
                # For JQL mode, provide field and value suggestions
                suggestions.extend(_get_jql_suggestions(db, query, limit=limit))

            elif mode == "regex":
                # For regex mode, provide pattern suggestions and matches
                suggestions.extend(_get_regex_suggestions(db, query, limit=limit))

            # Remove duplicates and limit results
            unique_suggestions = []
            seen = set()
            for sugg in suggestions:
                key = (sugg.get("type"), sugg.get("value"))
                if key not in seen:
                    seen.add(key)
                    unique_suggestions.append(sugg)
                if len(unique_suggestions) >= limit:
                    break

            return jsonify({"suggestions": unique_suggestions})

        except Exception as e:
            logger.error(f"Suggestion error: {e}")
            return jsonify({"suggestions": []})

    @app.route("/api/v1/issues/<issue_key>")
    @app.route("/api/issues/<issue_key>")  # Backward compatibility
    @apply_rate_limit
    @optional_api_key
    def api_issue_detail(issue_key):
        """Get detailed information for a specific issue.

        Args:
            issue_key: Jira issue key (e.g., 'PROJ-123')

        Returns:
        JSON response with issue details
        """
        try:
            # Query database for the specific issue
            import sqlite3

            with sqlite3.connect(db.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT * FROM issues WHERE key = ?
                """,
                    (issue_key,),
                )

                issue = cursor.fetchone()
                if not issue:
                    return jsonify({"error": "Issue not found"}), 404

                # Convert to dictionary and format response
                issue_dict = dict(issue)

                formatted_issue = {
                    "key": issue_dict["key"],
                    "summary": issue_dict["summary"],
                    "description": issue_dict["description"],
                    "status": {
                        "id": issue_dict["status_id"],
                        "name": issue_dict["status_name"],
                    },
                    "priority": {
                        "id": issue_dict["priority_id"],
                        "name": issue_dict["priority_name"],
                    },
                    "assignee": {
                        "key": issue_dict["assignee_key"],
                        "name": issue_dict["assignee_name"],
                        "display_name": issue_dict["assignee_display_name"],
                    },
                    "reporter": {
                        "key": issue_dict["reporter_key"],
                        "name": issue_dict["reporter_name"],
                        "display_name": issue_dict["reporter_display_name"],
                    },
                    "created": issue_dict["created"],
                    "updated": issue_dict["updated"],
                    "comments": issue_dict["comments"],
                    "labels": issue_dict.get("labels", ""),
                    "components": issue_dict.get("components", ""),
                    "project": {
                        "key": issue_dict["project_key"],
                        "name": issue_dict["project_name"],
                    },
                    "issue_type": issue_dict["issue_type"],
                    "custom_fields": {
                        "px_impact_score": issue_dict.get("custom_12322244"),
                        "product_manager": issue_dict.get("custom_12316752"),
                        "work_type": issue_dict.get("custom_12320040"),
                        "team": issue_dict.get("custom_12313240"),
                    },
                    "jira_url": f"{config.jira_url}/browse/{issue_key}",
                }

                return jsonify(formatted_issue)

        except Exception as e:
            logger.error(f"Issue detail error: {e}")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/v1/validate")
    @app.route("/api/validate")  # Backward compatibility
    @apply_rate_limit
    @optional_api_key
    def api_validate():
        """Validate JQL or regex query syntax.

        Query parameters:
        - q: Query to validate (required)
        - mode: Query mode ('jql' or 'regex', required)

        Returns:
        JSON response with validation result
        """
        query = request.args.get("q", "").strip()
        mode = request.args.get("mode", "").lower()

        if not query:
            return (
                jsonify({"valid": False, "error": 'Query parameter "q" is required'}),
                400,
            )

        if mode not in ["jql", "regex"]:
            return (
                jsonify({"valid": False, "error": 'Mode must be "jql" or "regex"'}),
                400,
            )

        try:
            if mode == "jql":
                is_valid, error_msg = search_engine.validate_jql(query)
            else:  # regex
                is_valid, error_msg = search_engine.validate_regex(query)

            return jsonify(
                {"valid": is_valid, "error": error_msg, "mode": mode, "query": query}
            )

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return (
                jsonify({"valid": False, "error": f"Validation failed: {str(e)}"}),
                500,
            )

    @app.route("/api/v1/config")
    @app.route("/api/config")  # Backward compatibility
    @optional_api_key
    def api_config():
        """Get client configuration (public settings only)."""
        try:
            return jsonify(
                {
                    "jira_url": config.jira_url,
                    "jira_base_url": config.jira_url.rstrip("/"),
                    "search_max_results": config.search_max_results,
                }
            )
        except Exception as e:
            logger.error(f"Config error: {e}")
            return jsonify({"error": "Failed to get configuration"}), 500

    @app.route("/api/v1/status")
    @app.route("/api/status")  # Backward compatibility
    @optional_api_key
    def api_status():
        """Get application status and statistics."""
        try:
            stats = db.get_statistics()
            return jsonify(
                {
                    "status": "healthy",
                    "database": {
                        "total_issues": stats["total_issues"],
                        "last_sync": stats["last_sync_time"],
                        "last_sync_query": stats["last_sync_query"],
                        "database_size_mb": stats["database_size_mb"],
                    },
                    "config": {
                        "jira_url": config.jira_url,
                        "search_max_results": config.search_max_results,
                        "custom_fields_count": len(config.custom_fields),
                    },
                }
            )
        except Exception as e:
            logger.error(f"Status error: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/api/v1/auth/info")
    @require_api_key
    def api_auth_info():
        """Get information about the current API key."""
        try:
            api_key_info = getattr(request, "api_key_info", {})
            return jsonify(
                {
                    "name": api_key_info.get("name", "Unknown"),
                    "created": api_key_info.get("created", "Unknown"),
                    "rate_limit": api_key_info.get("rate_limit", 60),
                    "enabled": api_key_info.get("enabled", False),
                }
            )
        except Exception as e:
            logger.error(f"Auth info error: {e}")
            return jsonify({"error": "Failed to get authentication info"}), 500

    @app.route("/api/v1")
    def api_v1_info():
        """API version 1 information."""
        return jsonify(
            {
                "version": "1.0.0",
                "name": "Jira Search API",
                "description": "Fast local Jira search interface",
                "documentation": "/api/v1/docs",
                "endpoints": {
                    "search": "/api/v1/search",
                    "suggest": "/api/v1/suggest",
                    "issues": "/api/v1/issues/{key}",
                    "validate": "/api/v1/validate",
                    "config": "/api/v1/config",
                    "status": "/api/v1/status",
                    "auth_info": "/api/v1/auth/info",
                },
                "authentication": {
                    "type": "API Key",
                    "header": "X-API-Key",
                    "required": False,
                    "note": "API key provides higher rate limits",
                },
                "rate_limits": {
                    "anonymous": "30 requests/minute",
                    "authenticated": "60-300 requests/minute (depends on key)",
                },
            }
        )

    @app.route("/api/v1/docs")
    def api_v1_docs():
        """Serve OpenAPI documentation."""
        try:
            # Look for OpenAPI spec file
            possible_paths = [
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "api",
                    "openapi.yaml",
                ),
                "api/openapi.yaml",
                "openapi.yaml",
            ]

            openapi_spec = None
            for path in possible_paths:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        openapi_spec = yaml.safe_load(f)
                    break

            if openapi_spec:
                # Update server URLs to match current request
                if "servers" not in openapi_spec:
                    openapi_spec["servers"] = []

                current_server = {
                    "url": f"{request.scheme}://{request.host}/api",
                    "description": "Current server",
                }

                # Add current server as first option
                openapi_spec["servers"].insert(0, current_server)

                return jsonify(openapi_spec)
            else:
                return (
                    jsonify(
                        {
                            "error": "OpenAPI specification not found",
                            "message": "The API documentation is not available",
                        }
                    ),
                    404,
                )

        except Exception as e:
            logger.error(f"Docs error: {e}")
            return (
                jsonify(
                    {"error": "Failed to load API documentation", "message": str(e)}
                ),
                500,
            )

    @app.route("/api/v1/docs/ui")
    def api_v1_docs_ui():
        """Serve interactive API documentation UI."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Jira Search API Documentation</title>
            <link rel="stylesheet" type="text/css"
                  href="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui.css" />
        </head>
        <body>
            <div id="swagger-ui"></div>
            <script src="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui-bundle.js">
            </script>
            <script>
                SwaggerUIBundle({
                    url: '/api/v1/docs',
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIBundle.presets.standalone
                    ],
                    plugins: [
                        SwaggerUIBundle.plugins.DownloadUrl
                    ],
                    layout: "StandaloneLayout"
                });
            </script>
        </body>
        </html>
        """

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({"error": "Internal server error"}), 500

    @app.after_request
    def after_request(response):
        """Add headers to all responses."""
        if request.path.startswith("/api/"):
            response = add_api_info_headers(response)
        return response

    return app
