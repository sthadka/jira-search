#!/bin/bash
# 
# Jira Search Mirror API Examples using curl
# 
# This script demonstrates how to use the Jira Search Mirror API with curl commands.
# It includes examples for all major API endpoints with proper error handling.
#

set -e  # Exit on error

# Configuration
BASE_URL="http://localhost:8080"
API_KEY="dev-key-12345"  # Optional: set your API key here

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to make API calls
api_call() {
    local method="$1"
    local endpoint="$2"
    local extra_args="${3:-}"
    
    echo -e "${BLUE}→ $method $endpoint${NC}"
    
    local headers="-H 'Content-Type: application/json'"
    if [ -n "$API_KEY" ]; then
        headers="$headers -H 'X-API-Key: $API_KEY'"
    fi
    
    local cmd="curl -s -X $method $extra_args $headers \"$BASE_URL/api/v1$endpoint\""
    echo -e "${YELLOW}Command:${NC} $cmd"
    
    local response=$(eval $cmd)
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}Response:${NC}"
        echo "$response" | jq '.' 2>/dev/null || echo "$response"
    else
        echo -e "${RED}Error: Command failed with exit code $exit_code${NC}"
    fi
    
    echo ""
    return $exit_code
}

# Helper function to check if jq is available
check_jq() {
    if ! command -v jq &> /dev/null; then
        echo -e "${YELLOW}Warning: jq is not installed. JSON responses will not be pretty-printed.${NC}"
        echo "Install jq for better output formatting: https://stedolan.github.io/jq/"
        echo ""
    fi
}

echo "🔍 Jira Search Mirror API Examples"
echo "================================="
echo ""

check_jq

# Test if server is running
echo -e "${BLUE}Testing server connectivity...${NC}"
if ! curl -s --connect-timeout 5 "$BASE_URL/api/v1" > /dev/null; then
    echo -e "${RED}❌ Cannot connect to $BASE_URL${NC}"
    echo "Make sure the Jira Search Mirror server is running:"
    echo "  python -m jira_search serve"
    exit 1
fi
echo -e "${GREEN}✅ Server is running${NC}"
echo ""

# 1. API Information
echo "📋 1. Getting API Information"
echo "=============================="
api_call "GET" ""

# 2. System Status
echo "📊 2. System Status"
echo "==================="
api_call "GET" "/status"

# 3. Configuration
echo "⚙️ 3. Configuration"
echo "==================="
api_call "GET" "/config"

# 4. Natural Language Search
echo "🔍 4. Natural Language Search"
echo "============================="
echo "Searching for 'security vulnerability' with natural language mode..."
api_call "GET" "/search" "-G -d 'q=security vulnerability' -d 'mode=natural' -d 'limit=3'"

# 5. JQL Search
echo "📋 5. JQL Search"
echo "================"
echo "Searching with JQL query..."

# First validate the JQL query
echo "Validating JQL query..."
jql_query="status = \"Open\" AND priority = \"High\""
api_call "GET" "/validate" "-G -d 'q=$jql_query' -d 'mode=jql'"

echo "Executing JQL search..."
api_call "GET" "/search" "-G -d 'q=$jql_query' -d 'mode=jql' -d 'limit=3'"

# 6. Regex Search
echo "🔤 6. Regex Search"
echo "=================="
echo "Searching with regex pattern..."

# First validate the regex
regex_pattern="ROX-\\d{5}"
api_call "GET" "/validate" "-G -d 'q=$regex_pattern' -d 'mode=regex'"

echo "Executing regex search..."
api_call "GET" "/search" "-G -d 'q=$regex_pattern' -d 'mode=regex' -d 'limit=3'"

# 7. Search Suggestions
echo "💡 7. Search Suggestions"
echo "========================"
echo "Getting suggestions for partial query 'ROX-'..."
api_call "GET" "/suggest" "-G -d 'q=ROX-' -d 'mode=natural' -d 'limit=5'"

echo "Getting JQL suggestions for 'project'..."
api_call "GET" "/suggest" "-G -d 'q=project' -d 'mode=jql' -d 'limit=5'"

# 8. Issue Details
echo "📄 8. Issue Details"
echo "==================="

# First get an issue key from search results
echo "Finding an issue to get details for..."
issue_key=$(curl -s -G "$BASE_URL/api/v1/search" -d 'q=ROX' -d 'limit=1' | jq -r '.results[0].key // empty' 2>/dev/null)

if [ -n "$issue_key" ] && [ "$issue_key" != "null" ]; then
    echo "Getting details for issue: $issue_key"
    api_call "GET" "/issues/$issue_key"
else
    echo -e "${YELLOW}No issues found to get details for. Using example key ROX-12345...${NC}"
    api_call "GET" "/issues/ROX-12345"
fi

# 9. API Key Authentication (if API key is provided)
if [ -n "$API_KEY" ]; then
    echo "🔑 9. API Key Authentication"
    echo "============================"
    echo "Getting API key information..."
    api_call "GET" "/auth/info"
else
    echo "🔑 9. API Key Authentication"
    echo "============================"
    echo -e "${YELLOW}No API key provided. Skipping authenticated endpoints.${NC}"
    echo "To test authentication, set API_KEY variable at the top of this script."
    echo ""
fi

# 10. Rate Limiting Demo
echo "⏰ 10. Rate Limiting Demo"
echo "========================="
echo "Making multiple rapid requests to demonstrate rate limiting..."

for i in {1..5}; do
    echo "Request $i:"
    response=$(curl -s -w "HTTP_CODE:%{http_code}" "$BASE_URL/api/v1/config")
    http_code=$(echo "$response" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
    response_body=$(echo "$response" | sed 's/HTTP_CODE:[0-9]*$//')
    
    if [ "$http_code" = "429" ]; then
        echo -e "${RED}Rate limited (HTTP 429)${NC}"
        echo "$response_body" | jq '.' 2>/dev/null || echo "$response_body"
        break
    else
        echo -e "${GREEN}Success (HTTP $http_code)${NC}"
    fi
    
    sleep 0.1  # Small delay between requests
done

echo ""
echo "✅ All examples completed!"
echo ""
echo "📚 Additional Resources:"
echo "- Interactive API docs: $BASE_URL/api/v1/docs/ui"
echo "- OpenAPI spec: $BASE_URL/api/v1/docs"
echo "- Python client example: python_client.py"