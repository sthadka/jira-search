#!/bin/bash

# Setup script for pre-commit hooks
set -e

echo "Setting up pre-commit hooks for Jira Search..."

# Check if .git directory exists
if [ ! -d ".git" ]; then
    echo "Error: This script must be run from the root of a git repository."
    exit 1
fi

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv not found. Please install uv first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p .git/hooks

# Copy pre-commit hook
if [ -f ".git/hooks/pre-commit" ]; then
    echo "Pre-commit hook already exists. Creating backup..."
    mv .git/hooks/pre-commit .git/hooks/pre-commit.backup
fi

# Create the pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash

# Pre-commit hook to run tests and linting
set -e

echo "Running pre-commit checks..."

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv not found. Please install uv first."
    exit 1
fi

# Run black formatting (auto-fix)
echo "Auto-formatting code with black..."
if ! uv run black src/jira_search; then
    echo "Error: Black formatting failed. Please check the errors above."
    exit 1
fi

# Run flake8 linting
echo "Running flake8 linting..."
if ! uv run flake8 src/jira_search --max-line-length=100; then
    echo "Error: Linting failed. Please fix the issues above."
    exit 1
fi

# Run tests
echo "Running tests..."
if ! uv run python -m pytest tests/ -v; then
    echo "Error: Tests failed. Please fix the failing tests."
    exit 1
fi

echo "All pre-commit checks passed!"
EOF

# Make the hook executable
chmod +x .git/hooks/pre-commit

echo "Pre-commit hook installed successfully!"
echo ""
echo "The hook will now run automatically before each commit and will:"
echo "  - Auto-format code (black)"
echo "  - Run code linting (flake8)"
echo "  - Run unit tests (pytest)"
echo ""
echo "To manually run the checks: .git/hooks/pre-commit"
echo "To format code: uv run black src/jira_search"
echo "To run tests: uv run python -m pytest tests/ -v"
