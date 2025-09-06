/**
 * Jira Search Mirror API JavaScript Client
 * 
 * This module provides a JavaScript client for the Jira Search Mirror API.
 * It can be used in both browser and Node.js environments.
 */

class JiraSearchClient {
    /**
     * Create a new Jira Search API client.
     * @param {Object} options - Configuration options
     * @param {string} options.baseUrl - Base URL of the API server
     * @param {string} [options.apiKey] - Optional API key for authentication
     * @param {number} [options.timeout=5000] - Request timeout in milliseconds
     */
    constructor({ baseUrl = 'http://localhost:8080', apiKey = null, timeout = 5000 } = {}) {
        this.baseUrl = baseUrl.replace(/\/+$/, ''); // Remove trailing slashes
        this.apiKey = apiKey;
        this.timeout = timeout;
        
        // Default headers
        this.defaultHeaders = {
            'Content-Type': 'application/json',
            'User-Agent': 'JiraSearchMirror-JS-Client/1.0'
        };
        
        if (this.apiKey) {
            this.defaultHeaders['X-API-Key'] = this.apiKey;
        }
    }
    
    /**
     * Make an HTTP request to the API.
     * @private
     * @param {string} method - HTTP method
     * @param {string} endpoint - API endpoint
     * @param {Object} [options={}] - Request options
     * @returns {Promise<Object>} Response data
     */
    async _request(method, endpoint, options = {}) {
        const url = `${this.baseUrl}/api/v1${endpoint}`;
        const { params = {}, data = null, headers = {} } = options;
        
        // Build query string for GET requests
        const searchParams = new URLSearchParams();
        Object.entries(params).forEach(([key, value]) => {
            if (value !== null && value !== undefined) {
                searchParams.append(key, value);
            }
        });
        
        const fullUrl = searchParams.toString() ? `${url}?${searchParams}` : url;
        
        const requestOptions = {
            method,
            headers: { ...this.defaultHeaders, ...headers },
        };
        
        if (data && method !== 'GET') {
            requestOptions.body = JSON.stringify(data);
        }
        
        // Add timeout support
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);
        requestOptions.signal = controller.signal;
        
        try {
            const response = await fetch(fullUrl, requestOptions);
            clearTimeout(timeoutId);
            
            const responseData = await response.json();
            
            if (!response.ok) {
                const error = new APIError(responseData.error || `HTTP ${response.status}`);
                error.status = response.status;
                error.response = responseData;
                
                if (response.status === 429) {
                    error.retryAfter = parseInt(response.headers.get('Retry-After') || '60');
                }
                
                throw error;
            }
            
            return responseData;
        } catch (error) {
            clearTimeout(timeoutId);
            
            if (error.name === 'AbortError') {
                throw new APIError(`Request timeout after ${this.timeout}ms`);
            }
            
            throw error;
        }
    }
    
    /**
     * Search for issues.
     * @param {string} query - Search query
     * @param {Object} [options={}] - Search options
     * @param {string} [options.mode='natural'] - Search mode ('natural', 'jql', 'regex')
     * @param {number} [options.limit=100] - Maximum results
     * @param {number} [options.offset=0] - Pagination offset
     * @returns {Promise<Object>} Search results
     */
    async search(query, { mode = 'natural', limit = 100, offset = 0 } = {}) {
        return this._request('GET', '/search', {
            params: { q: query, mode, limit, offset }
        });
    }
    
    /**
     * Get search suggestions.
     * @param {string} query - Partial query
     * @param {Object} [options={}] - Suggestion options
     * @param {string} [options.mode='natural'] - Search mode
     * @param {number} [options.limit=8] - Maximum suggestions
     * @returns {Promise<Array>} List of suggestions
     */
    async getSuggestions(query, { mode = 'natural', limit = 8 } = {}) {
        const response = await this._request('GET', '/suggest', {
            params: { q: query, mode, limit }
        });
        return response.suggestions;
    }
    
    /**
     * Get detailed issue information.
     * @param {string} issueKey - Jira issue key (e.g., 'ROX-12345')
     * @returns {Promise<Object>} Issue details
     */
    async getIssue(issueKey) {
        return this._request('GET', `/issues/${issueKey}`);
    }
    
    /**
     * Validate a JQL or regex query.
     * @param {string} query - Query to validate
     * @param {string} mode - Query mode ('jql' or 'regex')
     * @returns {Promise<Object>} Validation result
     */
    async validateQuery(query, mode) {
        return this._request('GET', '/validate', {
            params: { q: query, mode }
        });
    }
    
    /**
     * Get client configuration.
     * @returns {Promise<Object>} Configuration
     */
    async getConfig() {
        return this._request('GET', '/config');
    }
    
    /**
     * Get system status.
     * @returns {Promise<Object>} System status
     */
    async getStatus() {
        return this._request('GET', '/status');
    }
    
    /**
     * Get API key information (requires authentication).
     * @returns {Promise<Object>} Authentication info
     */
    async getAuthInfo() {
        return this._request('GET', '/auth/info');
    }
    
    /**
     * Get API information.
     * @returns {Promise<Object>} API info
     */
    async getApiInfo() {
        return this._request('GET', '');
    }
}

/**
 * Custom error class for API errors.
 */
class APIError extends Error {
    constructor(message) {
        super(message);
        this.name = 'APIError';
    }
}

// Example usage function
async function example() {
    console.log('🔍 Jira Search Mirror API JavaScript Client Example');
    console.log('====================================================');
    
    // Initialize client
    // For authenticated requests, provide an API key:
    // const client = new JiraSearchClient({ apiKey: 'dev-key-12345' });
    const client = new JiraSearchClient();
    
    try {
        // 1. Get API info
        console.log('📋 Getting API information...');
        const apiInfo = await client.getApiInfo();
        console.log(`API Version: ${apiInfo.version}`);
        console.log(`Description: ${apiInfo.description}`);
        console.log('');
        
        // 2. Get system status
        console.log('📊 Getting system status...');
        const status = await client.getStatus();
        console.log(`Status: ${status.status}`);
        console.log(`Total issues: ${status.database.total_issues.toLocaleString()}`);
        console.log(`Last sync: ${status.database.last_sync}`);
        console.log('');
        
        // 3. Natural language search
        console.log('🔍 Natural language search for "security vulnerability"...');
        const searchResults = await client.search('security vulnerability', { 
            mode: 'natural', 
            limit: 5 
        });
        
        console.log(`Found ${searchResults.total} total results (showing first 5)`);
        console.log(`Query time: ${searchResults.query_time_ms}ms`);
        
        searchResults.results.forEach(issue => {
            console.log(`  • ${issue.key}: ${issue.summary}`);
            console.log(`    Status: ${issue.status_name}, Priority: ${issue.priority_name}`);
            console.log(`    Assignee: ${issue.assignee_display_name || 'Unassigned'}`);
        });
        console.log('');
        
        // 4. JQL search with validation
        console.log('📋 JQL search for open high priority issues...');
        const jqlQuery = 'status = "Open" AND priority = "High"';
        
        // Validate query first
        const validation = await client.validateQuery(jqlQuery, 'jql');
        if (validation.valid) {
            console.log(`✅ JQL query is valid: ${jqlQuery}`);
            
            const jqlResults = await client.search(jqlQuery, { mode: 'jql', limit: 3 });
            console.log(`Found ${jqlResults.total} high priority open issues (showing first 3)`);
            
            jqlResults.results.forEach(issue => {
                console.log(`  • ${issue.key}: ${issue.summary}`);
                console.log(`    Created: ${issue.created}`);
            });
        } else {
            console.log(`❌ Invalid JQL query: ${validation.error}`);
        }
        console.log('');
        
        // 5. Get suggestions
        console.log('💡 Getting suggestions for "ROX-"...');
        const suggestions = await client.getSuggestions('ROX-', { 
            mode: 'natural', 
            limit: 5 
        });
        
        suggestions.forEach(suggestion => {
            console.log(`  ${suggestion.icon} ${suggestion.label}`);
        });
        console.log('');
        
        // 6. Get specific issue details
        if (searchResults.results.length > 0) {
            const issueKey = searchResults.results[0].key;
            console.log(`📄 Getting details for ${issueKey}...`);
            
            const issueDetails = await client.getIssue(issueKey);
            console.log(`Summary: ${issueDetails.summary}`);
            console.log(`Status: ${issueDetails.status.name}`);
            console.log(`Priority: ${issueDetails.priority.name}`);
            console.log(`Project: ${issueDetails.project.name}`);
            console.log(`Jira URL: ${issueDetails.jira_url}`);
            
            if (issueDetails.labels) {
                console.log(`Labels: ${issueDetails.labels}`);
            }
            if (issueDetails.components) {
                console.log(`Components: ${issueDetails.components}`);
            }
        }
        console.log('');
        
        // 7. API key info (if authenticated)
        if (client.apiKey) {
            try {
                console.log('🔑 Getting API key information...');
                const authInfo = await client.getAuthInfo();
                console.log(`Key name: ${authInfo.name}`);
                console.log(`Rate limit: ${authInfo.rate_limit} requests/minute`);
                console.log(`Created: ${authInfo.created}`);
            } catch (error) {
                if (error.status === 401) {
                    console.log('❌ API key authentication failed');
                } else {
                    throw error;
                }
            }
        }
        
        console.log('✅ Example completed successfully!');
        
    } catch (error) {
        if (error instanceof APIError) {
            console.error(`❌ API Error: ${error.message}`);
            if (error.status === 429) {
                console.error(`⏰ Rate limit exceeded. Retry after ${error.retryAfter} seconds`);
            }
        } else {
            console.error(`💥 Unexpected error: ${error.message}`);
        }
    }
}

// Export for different environments
if (typeof module !== 'undefined' && module.exports) {
    // Node.js environment
    module.exports = { JiraSearchClient, APIError, example };
} else if (typeof window !== 'undefined') {
    // Browser environment
    window.JiraSearchClient = JiraSearchClient;
    window.APIError = APIError;
    window.jiraSearchExample = example;
}

// Run example if this file is executed directly in Node.js
if (typeof require !== 'undefined' && require.main === module) {
    example();
}