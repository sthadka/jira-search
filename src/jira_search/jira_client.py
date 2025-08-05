"""Jira API client with Personal Access Token authentication."""

import requests
import time
import logging
from typing import Dict, List, Optional, Any, Generator
from requests.exceptions import RequestException, HTTPError, Timeout
from jira_search.config import Config

logger = logging.getLogger(__name__)


class JiraClientError(Exception):
    """Jira client related errors."""
    pass


class JiraAuthenticationError(JiraClientError):
    """Jira authentication errors."""
    pass


class JiraRateLimitError(JiraClientError):
    """Jira rate limit errors."""
    pass


class JiraClient:
    """Jira API client with PAT authentication and rate limiting."""
    
    def __init__(self, config: Config):
        """Initialize Jira client.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.base_url = config.jira_url
        self.username = config.jira_username
        self.pat = config.jira_pat
        
        # Rate limiting
        self.rate_limit = config.sync_rate_limit
        self.last_request_time = 0
        self.min_request_interval = 60.0 / self.rate_limit  # seconds between requests
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.auth = (self.username, self.pat)
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect rate limiting."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated API request with rate limiting and error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (relative to base URL)
            **kwargs: Additional arguments passed to requests
            
        Returns:
            Response object
            
        Raises:
            JiraAuthenticationError: For authentication failures
            JiraRateLimitError: For rate limit exceeded
            JiraClientError: For other API errors
        """
        self._wait_for_rate_limit()
        
        url = f"{self.base_url}/rest/api/2/{endpoint.lstrip('/')}"
        
        try:
            logger.debug(f"Making {method} request to {url}")
            response = self.session.request(method, url, timeout=30, **kwargs)
            
            if response.status_code == 401:
                raise JiraAuthenticationError(
                    "Authentication failed. Please check your username and Personal Access Token."
                )
            elif response.status_code == 403:
                raise JiraAuthenticationError(
                    "Access forbidden. Please check your permissions in Jira."
                )
            elif response.status_code == 429:
                raise JiraRateLimitError(
                    "Rate limit exceeded. Try reducing the rate_limit in config.yaml."
                )
            
            response.raise_for_status()
            return response
            
        except Timeout:
            raise JiraClientError("Request timed out. Please check your network connection.")
        except HTTPError as e:
            if e.response.status_code >= 500:
                raise JiraClientError(f"Jira server error ({e.response.status_code}): {e}")
            else:
                raise JiraClientError(f"HTTP error ({e.response.status_code}): {e}")
        except RequestException as e:
            raise JiraClientError(f"Network error: {e}")
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Jira and validate credentials.
        
        Returns:
            Dictionary with connection test results
            
        Raises:
            JiraClientError: If connection fails
        """
        try:
            logger.info("Testing Jira connection...")
            
            # Test basic connectivity with /myself endpoint
            response = self._make_request('GET', 'myself')
            user_info = response.json()
            
            logger.info(f"Successfully connected as user: {user_info.get('displayName', 'Unknown')}")
            
            return {
                'success': True,
                'user': user_info.get('displayName'),
                'username': user_info.get('name'),
                'email': user_info.get('emailAddress'),
                'jira_version': self._get_server_info().get('version', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_server_info(self) -> Dict[str, Any]:
        """Get Jira server information."""
        try:
            response = self._make_request('GET', 'serverInfo')
            return response.json()
        except Exception:
            return {}
    
    def search_issues(self, jql: str, start_at: int = 0, max_results: int = 100, 
                     fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Search for issues using JQL.
        
        Args:
            jql: JQL query string
            start_at: Starting index for pagination
            max_results: Maximum number of results to return
            fields: List of fields to include in response
            
        Returns:
            Search results from Jira API
            
        Raises:
            JiraClientError: If search fails
        """
        if fields is None:
            fields = [
                'key', 'summary', 'description', 'status', 'priority',
                'assignee', 'reporter', 'created', 'updated', 'comment'
            ]
            # Add custom fields from config
            for custom_field in self.config.custom_fields:
                fields.append(custom_field['id'])
        
        params = {
            'jql': jql,
            'startAt': start_at,
            'maxResults': max_results,
            'fields': ','.join(fields),
            'expand': 'names'
        }
        
        logger.debug(f"Searching issues with JQL: {jql}")
        response = self._make_request('GET', 'search', params=params)
        result = response.json()
        
        logger.debug(f"Found {result.get('total', 0)} issues, returned {len(result.get('issues', []))}")
        return result
    
    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get a single issue by key.
        
        Args:
            issue_key: Jira issue key (e.g., 'PROJ-123')
            fields: List of fields to include in response
            
        Returns:
            Issue data from Jira API
            
        Raises:
            JiraClientError: If issue not found or request fails
        """
        if fields is None:
            fields = ['*all']
        
        params = {
            'fields': ','.join(fields),
            'expand': 'names'
        }
        
        logger.debug(f"Getting issue: {issue_key}")
        response = self._make_request('GET', f'issue/{issue_key}', params=params)
        return response.json()
    
    def search_issues_paginated(self, jql: str, batch_size: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Search for issues with automatic pagination.
        
        Args:
            jql: JQL query string
            batch_size: Number of issues per request (defaults to config batch_size)
            
        Yields:
            Individual issue dictionaries
            
        Raises:
            JiraClientError: If search fails
        """
        if batch_size is None:
            batch_size = self.config.sync_batch_size
        
        start_at = 0
        total = None
        
        while True:
            result = self.search_issues(jql, start_at=start_at, max_results=batch_size)
            
            if total is None:
                total = result.get('total', 0)
                logger.info(f"Starting paginated search for {total} issues")
            
            issues = result.get('issues', [])
            if not issues:
                break
            
            for issue in issues:
                yield issue
            
            start_at += len(issues)
            logger.debug(f"Processed {start_at}/{total} issues")
            
            if start_at >= total:
                break
    
    def validate_jql(self, jql: str) -> bool:
        """Validate JQL query syntax.
        
        Args:
            jql: JQL query string
            
        Returns:
            True if JQL is valid, False otherwise
        """
        try:
            # Try to search with maxResults=0 to validate syntax without retrieving data
            self.search_issues(jql, max_results=0)
            return True
        except JiraClientError:
            return False