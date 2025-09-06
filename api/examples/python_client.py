#!/usr/bin/env python3
"""
Example Python client for Jira Search Mirror API.

This script demonstrates how to use the Jira Search Mirror API with Python.
It includes examples for all major API endpoints with proper error handling.
"""

import requests
import json
import time
from typing import Dict, List, Optional, Any


class JiraSearchClient:
    """Python client for Jira Search Mirror API."""
    
    def __init__(self, base_url: str = "http://localhost:8080", api_key: Optional[str] = None):
        """Initialize the client.
        
        Args:
            base_url: Base URL of the Jira Search Mirror server
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
        if self.api_key:
            self.session.headers.update({'X-API-Key': self.api_key})
        
        # Set user agent
        self.session.headers.update({
            'User-Agent': 'JiraSearchMirror-Python-Client/1.0'
        })
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make HTTP request with error handling.
        
        Args:
            method: HTTP method
            endpoint: API endpoint path
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object
            
        Raises:
            requests.RequestException: On HTTP errors
        """
        url = f"{self.base_url}/api/v1{endpoint}"
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', 60))
                raise RateLimitError(f"Rate limit exceeded. Retry after {retry_after} seconds.", retry_after)
            elif e.response.status_code == 401:
                raise AuthenticationError("Invalid or missing API key")
            else:
                try:
                    error_data = e.response.json()
                    raise APIError(f"API Error: {error_data.get('error', str(e))}")
                except ValueError:
                    raise APIError(f"HTTP Error: {e}")
        except requests.exceptions.RequestException as e:
            raise APIError(f"Request failed: {e}")
    
    def search(self, query: str, mode: str = "natural", limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Search for issues.
        
        Args:
            query: Search query
            mode: Search mode ('natural', 'jql', 'regex')
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            Search results dictionary
        """
        params = {
            'q': query,
            'mode': mode,
            'limit': limit,
            'offset': offset
        }
        
        response = self._make_request('GET', '/search', params=params)
        return response.json()
    
    def get_suggestions(self, query: str, mode: str = "natural", limit: int = 8) -> List[Dict[str, Any]]:
        """Get search suggestions.
        
        Args:
            query: Partial query
            mode: Search mode
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        params = {
            'q': query,
            'mode': mode,
            'limit': limit
        }
        
        response = self._make_request('GET', '/suggest', params=params)
        return response.json()['suggestions']
    
    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Get detailed issue information.
        
        Args:
            issue_key: Jira issue key (e.g., 'ROX-12345')
            
        Returns:
            Issue details dictionary
        """
        response = self._make_request('GET', f'/issues/{issue_key}')
        return response.json()
    
    def validate_query(self, query: str, mode: str) -> Dict[str, Any]:
        """Validate JQL or regex query.
        
        Args:
            query: Query to validate
            mode: Query mode ('jql' or 'regex')
            
        Returns:
            Validation result
        """
        params = {
            'q': query,
            'mode': mode
        }
        
        response = self._make_request('GET', '/validate', params=params)
        return response.json()
    
    def get_config(self) -> Dict[str, Any]:
        """Get client configuration.
        
        Returns:
            Configuration dictionary
        """
        response = self._make_request('GET', '/config')
        return response.json()
    
    def get_status(self) -> Dict[str, Any]:
        """Get system status.
        
        Returns:
            Status dictionary
        """
        response = self._make_request('GET', '/status')
        return response.json()
    
    def get_auth_info(self) -> Dict[str, Any]:
        """Get API key information (requires authentication).
        
        Returns:
            Authentication info dictionary
        """
        response = self._make_request('GET', '/auth/info')
        return response.json()


class APIError(Exception):
    """Base API error."""
    pass


class AuthenticationError(APIError):
    """Authentication error."""
    pass


class RateLimitError(APIError):
    """Rate limit error."""
    
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


def main():
    """Example usage of the Jira Search Mirror API client."""
    print("🔍 Jira Search Mirror API Client Example")
    print("=" * 50)
    
    # Initialize client
    # For authenticated requests, provide an API key:
    # client = JiraSearchClient(api_key="dev-key-12345")
    client = JiraSearchClient()
    
    try:
        # 1. Get system status
        print("📊 Getting system status...")
        status = client.get_status()
        print(f"Status: {status['status']}")
        print(f"Total issues: {status['database']['total_issues']:,}")
        print(f"Last sync: {status['database']['last_sync']}")
        print()
        
        # 2. Get configuration
        print("⚙️ Getting configuration...")
        config = client.get_config()
        print(f"Jira URL: {config['jira_url']}")
        print(f"Max results: {config['search_max_results']}")
        print()
        
        # 3. Natural language search
        print("🔍 Natural language search for 'security vulnerability'...")
        search_results = client.search("security vulnerability", mode="natural", limit=5)
        print(f"Found {search_results['total']} total results (showing first 5)")
        print(f"Query time: {search_results['query_time_ms']}ms")
        
        for issue in search_results['results']:
            print(f"  • {issue['key']}: {issue['summary']}")
            print(f"    Status: {issue['status_name']}, Priority: {issue['priority_name']}")
            print(f"    Assignee: {issue['assignee_display_name'] or 'Unassigned'}")
        print()
        
        # 4. JQL search
        print("📋 JQL search for open issues...")
        jql_query = 'status = "Open" AND priority = "High"'
        
        # First validate the query
        validation = client.validate_query(jql_query, "jql")
        if validation['valid']:
            print(f"✅ JQL query is valid: {jql_query}")
            
            jql_results = client.search(jql_query, mode="jql", limit=3)
            print(f"Found {jql_results['total']} high priority open issues (showing first 3)")
            
            for issue in jql_results['results']:
                print(f"  • {issue['key']}: {issue['summary']}")
                print(f"    Created: {issue['created']}")
        else:
            print(f"❌ Invalid JQL query: {validation['error']}")
        print()
        
        # 5. Get suggestions
        print("💡 Getting suggestions for 'ROX-'...")
        suggestions = client.get_suggestions("ROX-", mode="natural", limit=5)
        for suggestion in suggestions:
            print(f"  {suggestion['icon']} {suggestion['label']}")
        print()
        
        # 6. Get specific issue details
        if search_results['results']:
            issue_key = search_results['results'][0]['key']
            print(f"📄 Getting details for {issue_key}...")
            
            issue_details = client.get_issue(issue_key)
            print(f"Summary: {issue_details['summary']}")
            print(f"Status: {issue_details['status']['name']}")
            print(f"Priority: {issue_details['priority']['name']}")
            print(f"Project: {issue_details['project']['name']}")
            print(f"Jira URL: {issue_details['jira_url']}")
            
            if issue_details['labels']:
                print(f"Labels: {issue_details['labels']}")
            if issue_details['components']:
                print(f"Components: {issue_details['components']}")
        print()
        
        # 7. API key info (if authenticated)
        if client.api_key:
            try:
                print("🔑 Getting API key information...")
                auth_info = client.get_auth_info()
                print(f"Key name: {auth_info['name']}")
                print(f"Rate limit: {auth_info['rate_limit']} requests/minute")
                print(f"Created: {auth_info['created']}")
            except AuthenticationError:
                print("❌ API key authentication failed")
        
        print("✅ Example completed successfully!")
        
    except RateLimitError as e:
        print(f"⏰ Rate limit exceeded: {e}")
        print(f"Retry after {e.retry_after} seconds")
    except APIError as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")


if __name__ == "__main__":
    main()