"""Web interface for Jira Search Mirror."""

import time
import logging
from flask import Flask, render_template, request, jsonify
from jira_search.config import Config
from jira_search.database import Database, DatabaseError
from jira_search.search import AdvancedSearch, SearchError, JQLError, RegexError

logger = logging.getLogger(__name__)


def create_app(config: Config) -> Flask:
    """Create and configure Flask application.
    
    Args:
        config: Configuration object
        
    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'jira-search-secret-key'  # For session management
    
    # Initialize database connection and search engine
    db = Database(config)
    search_engine = AdvancedSearch(db, timeout_seconds=config.search_timeout_seconds)
    
    @app.route('/')
    def index():
        """Main search interface."""
        try:
            # Get database statistics for display
            stats = db.get_statistics()
            return render_template('index.html', stats=stats)
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return render_template('error.html', error="Database not available"), 500
    
    @app.route('/api/search')
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
        query = request.args.get('q', '').strip()
        limit = min(int(request.args.get('limit', 100)), config.search_max_results)
        offset = int(request.args.get('offset', 0))
        mode = request.args.get('mode', 'natural')
        
        if not query:
            return jsonify({
                'error': 'Query parameter "q" is required',
                'results': [],
                'total': 0,
                'query_time_ms': 0
            }), 400
        
        try:
            # Perform search using advanced search engine
            results, total = search_engine.search(query, mode, limit=limit, offset=offset)
            
            # Calculate query time
            query_time_ms = int((time.time() - start_time) * 1000)
            
            # Format results for JSON response
            formatted_results = []
            for result in results:
                formatted_result = {
                    'key': result['key'],
                    'summary': result['summary'],
                    'status_name': result['status_name'],
                    'priority_name': result['priority_name'],
                    'assignee_display_name': result['assignee_display_name'],
                    'reporter_display_name': result['reporter_display_name'],
                    'created': result['created'],
                    'updated': result['updated'],
                    'project_key': result['project_key'],
                    'project_name': result['project_name'],
                    'issue_type': result['issue_type'],
                    'custom_fields': {
                        'px_impact_score': result.get('custom_12322244'),
                        'product_manager': result.get('custom_12316752'),
                        'work_type': result.get('custom_12320040'),
                        'team': result.get('custom_12313240')
                    }
                }
                formatted_results.append(formatted_result)
            
            return jsonify({
                'results': formatted_results,
                'total': total,
                'query': query,
                'mode': mode,
                'limit': limit,
                'offset': offset,
                'query_time_ms': query_time_ms
            })
            
        except (SearchError, JQLError, RegexError) as e:
            logger.error(f"Search error: {e}")
            return jsonify({
                'error': str(e),
                'results': [],
                'total': 0,
                'query_time_ms': int((time.time() - start_time) * 1000)
            }), 400
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return jsonify({
                'error': f'Database error: {str(e)}',
                'results': [],
                'total': 0,
                'query_time_ms': int((time.time() - start_time) * 1000)
            }), 500
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return jsonify({
                'error': 'Internal server error',
                'results': [],
                'total': 0,
                'query_time_ms': int((time.time() - start_time) * 1000)
            }), 500
    
    @app.route('/api/suggest')
    def api_suggest():
        """Type-ahead suggestions API endpoint.
        
        Query parameters:
        - q: Partial query (required)
        - limit: Maximum suggestions (default: 10)
        
        Returns:
        JSON response with suggestions
        """
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 10))
        
        if not query or len(query) < 2:
            return jsonify({'suggestions': []})
        
        try:
            # For now, return top search results as suggestions
            # TODO: Implement proper type-ahead suggestions in Phase 5
            results, _ = db.search_issues(query, limit=limit)
            suggestions = [
                {
                    'key': result['key'],
                    'summary': result['summary'][:100] + '...' if len(result['summary']) > 100 else result['summary']
                }
                for result in results
            ]
            
            return jsonify({'suggestions': suggestions})
            
        except Exception as e:
            logger.error(f"Suggestion error: {e}")
            return jsonify({'suggestions': []})
    
    @app.route('/api/issues/<issue_key>')
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
                cursor = conn.execute("""
                    SELECT * FROM issues WHERE key = ?
                """, (issue_key,))
                
                issue = cursor.fetchone()
                if not issue:
                    return jsonify({'error': 'Issue not found'}), 404
                
                # Convert to dictionary and format response
                issue_dict = dict(issue)
                
                formatted_issue = {
                    'key': issue_dict['key'],
                    'summary': issue_dict['summary'],
                    'description': issue_dict['description'],
                    'status': {
                        'id': issue_dict['status_id'],
                        'name': issue_dict['status_name']
                    },
                    'priority': {
                        'id': issue_dict['priority_id'],
                        'name': issue_dict['priority_name']
                    },
                    'assignee': {
                        'key': issue_dict['assignee_key'],
                        'name': issue_dict['assignee_name'],
                        'display_name': issue_dict['assignee_display_name']
                    },
                    'reporter': {
                        'key': issue_dict['reporter_key'],
                        'name': issue_dict['reporter_name'],
                        'display_name': issue_dict['reporter_display_name']
                    },
                    'created': issue_dict['created'],
                    'updated': issue_dict['updated'],
                    'comments': issue_dict['comments'],
                    'project': {
                        'key': issue_dict['project_key'],
                        'name': issue_dict['project_name']
                    },
                    'issue_type': issue_dict['issue_type'],
                    'custom_fields': {
                        'px_impact_score': issue_dict.get('custom_12322244'),
                        'product_manager': issue_dict.get('custom_12316752'),
                        'work_type': issue_dict.get('custom_12320040'),
                        'team': issue_dict.get('custom_12313240')
                    },
                    'jira_url': f"{config.jira_url}/browse/{issue_key}"
                }
                
                return jsonify(formatted_issue)
                
        except Exception as e:
            logger.error(f"Issue detail error: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    @app.route('/api/validate')
    def api_validate():
        """Validate JQL or regex query syntax.
        
        Query parameters:
        - q: Query to validate (required)
        - mode: Query mode ('jql' or 'regex', required)
        
        Returns:
        JSON response with validation result
        """
        query = request.args.get('q', '').strip()
        mode = request.args.get('mode', '').lower()
        
        if not query:
            return jsonify({
                'valid': False,
                'error': 'Query parameter "q" is required'
            }), 400
        
        if mode not in ['jql', 'regex']:
            return jsonify({
                'valid': False,
                'error': 'Mode must be "jql" or "regex"'
            }), 400
        
        try:
            if mode == 'jql':
                is_valid, error_msg = search_engine.validate_jql(query)
            else:  # regex
                is_valid, error_msg = search_engine.validate_regex(query)
            
            return jsonify({
                'valid': is_valid,
                'error': error_msg,
                'mode': mode,
                'query': query
            })
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return jsonify({
                'valid': False,
                'error': f'Validation failed: {str(e)}'
            }), 500
    
    @app.route('/api/status')
    def api_status():
        """Get application status and statistics."""
        try:
            stats = db.get_statistics()
            return jsonify({
                'status': 'healthy',
                'database': {
                    'total_issues': stats['total_issues'],
                    'last_sync': stats['last_sync_time'],
                    'last_sync_query': stats['last_sync_query'],
                    'database_size_mb': stats['database_size_mb']
                },
                'config': {
                    'jira_url': config.jira_url,
                    'search_max_results': config.search_max_results,
                    'custom_fields_count': len(config.custom_fields)
                }
            })
        except Exception as e:
            logger.error(f"Status error: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({'error': 'Internal server error'}), 500
    
    return app