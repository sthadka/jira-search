"""Configuration management for Jira Search."""

import os
import yaml
import re
from typing import Dict, List, Optional, Any


class ConfigError(Exception):
    """Configuration-related errors."""

    pass


class Config:
    """Configuration manager for Jira Search."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration.

        Args:
            config_path: Path to config.yaml file. Defaults to './config.yaml'
        """
        self.config_path = config_path or "config.yaml"
        self.data = {}
        self.load()

    def load(self) -> None:
        """Load configuration from YAML file with environment variable support."""
        if not os.path.exists(self.config_path):
            raise ConfigError(
                f"Configuration file not found: {self.config_path}\n"
                f"Copy config.yaml.example to {self.config_path} and update with your details."
            )

        try:
            with open(self.config_path, "r") as f:
                content = f.read()
                # Replace environment variables in format ${VAR_NAME} or ${VAR_NAME:default}
                content = self._substitute_env_vars(content)
                self.data = yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to read config file: {e}")

        self.validate()

    def _substitute_env_vars(self, content: str) -> str:
        """Substitute environment variables in config content."""

        def replace_env_var(match):
            # Get the full match and check if it's in a comment
            full_match = match.group(0)
            start_pos = match.start()

            # Find the start of the line
            line_start = content.rfind("\n", 0, start_pos) + 1
            line_before_match = content[line_start:start_pos]

            # If there's a # before the match on the same line, skip substitution
            if "#" in line_before_match:
                return full_match

            var_expr = match.group(1)
            if ":" in var_expr:
                var_name, default_value = var_expr.split(":", 1)
                return os.getenv(var_name.strip(), default_value.strip())
            else:
                var_name = var_expr.strip()
                value = os.getenv(var_name)
                if value is None:
                    raise ConfigError(
                        f"Environment variable {var_name} is not set and no default provided"
                    )
                return value

        # Pattern to match ${VAR_NAME} or ${VAR_NAME:default}
        pattern = r"\$\{([^}]+)\}"
        return re.sub(pattern, replace_env_var, content)

    def validate(self) -> None:
        """Validate configuration with comprehensive checks."""
        errors = []
        warnings = []

        # Jira configuration validation
        jira_config = self.data.get("jira", {})
        if not jira_config:
            errors.append("jira section is required")
        else:
            url = jira_config.get("url")
            if not url:
                errors.append("jira.url is required")
            elif not url.startswith(("http://", "https://")):
                errors.append("jira.url must start with http:// or https://")

            if not jira_config.get("username"):
                errors.append("jira.username is required")

            if not jira_config.get("pat"):
                errors.append("jira.pat (Personal Access Token) is required")

        # Sync configuration validation
        sync_config = self.data.get("sync", {})
        if not sync_config:
            errors.append("sync section is required")
        else:
            project_key = sync_config.get("project_key")
            jql = sync_config.get("jql")
            if not project_key and not jql:
                errors.append("Either sync.project_key or sync.jql must be specified")

            # Validate rate limiting
            rate_limit = sync_config.get("rate_limit", 100)
            if not isinstance(rate_limit, int) or rate_limit <= 0:
                errors.append("sync.rate_limit must be a positive integer")
            elif rate_limit > 1000:
                warnings.append(
                    "sync.rate_limit > 1000 may cause issues with Jira API limits"
                )

            # Validate batch size
            batch_size = sync_config.get("batch_size", 100)
            if not isinstance(batch_size, int) or batch_size <= 0:
                errors.append("sync.batch_size must be a positive integer")
            elif batch_size > 1000:
                warnings.append("sync.batch_size > 1000 may cause memory issues")

        # Search configuration validation
        search_config = self.data.get("search", {})
        if search_config:
            max_results = search_config.get("max_results", 1000)
            if not isinstance(max_results, int) or max_results <= 0:
                errors.append("search.max_results must be a positive integer")

            timeout = search_config.get("timeout_seconds", 5)
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                errors.append("search.timeout_seconds must be a positive number")

        # Custom fields validation
        custom_fields = self.data.get("custom_fields", [])
        if custom_fields and not isinstance(custom_fields, list):
            errors.append("custom_fields must be a list")
        else:
            for i, field in enumerate(custom_fields):
                if not isinstance(field, dict):
                    errors.append(f"custom_fields[{i}] must be an object")
                    continue

                if not field.get("id"):
                    errors.append(f"custom_fields[{i}].id is required")
                elif not field["id"].startswith("customfield_"):
                    warnings.append(
                        f"custom_fields[{i}].id should typically start with 'customfield_'"
                    )

                if not field.get("name"):
                    errors.append(f"custom_fields[{i}].name is required")

                field_type = field.get("type", "text")
                if field_type not in [
                    "text",
                    "number",
                    "select",
                    "multiselect",
                    "date",
                ]:
                    warnings.append(
                        f"custom_fields[{i}].type '{field_type}' is not a recognized type"
                    )

        # Database configuration validation
        db_config = self.data.get("database", {})
        if db_config:
            db_path = db_config.get("path")
            if db_path:
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    warnings.append(f"Database directory does not exist: {db_dir}")

        # Fields configuration validation
        fields_config = self.data.get("fields", {})
        if fields_config:
            core_fields = fields_config.get("core")
            if core_fields and not isinstance(core_fields, list):
                errors.append("fields.core must be a list")
            elif core_fields:
                required_fields = ["key", "summary"]  # Minimum required
                for req_field in required_fields:
                    if req_field not in core_fields:
                        errors.append(
                            f"fields.core must include required field: {req_field}"
                        )

            search_fields = fields_config.get("search")
            if search_fields and not isinstance(search_fields, list):
                errors.append("fields.search must be a list")
            elif search_fields and core_fields:
                # Ensure all search fields are also in core fields
                for search_field in search_fields:
                    if search_field not in core_fields:
                        warnings.append(
                            f"Search field '{search_field}' is not in core fields list"
                        )

        # Report validation results
        if warnings:
            import logging

            logger = logging.getLogger(__name__)
            for warning in warnings:
                logger.warning(f"Configuration warning: {warning}")

        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(
                f"- {error}" for error in errors
            )
            if warnings:
                error_msg += "\n\nWarnings:\n" + "\n".join(
                    f"- {warning}" for warning in warnings
                )
            raise ConfigError(error_msg)

    @property
    def jira_url(self) -> str:
        """Get Jira base URL."""
        return self.data["jira"]["url"].rstrip("/")

    @property
    def jira_username(self) -> str:
        """Get Jira username."""
        return self.data["jira"]["username"]

    @property
    def jira_pat(self) -> str:
        """Get Jira Personal Access Token."""
        return self.data["jira"]["pat"]

    @property
    def sync_project_key(self) -> Optional[str]:
        """Get project key for syncing."""
        return self.data.get("sync", {}).get("project_key")

    @property
    def sync_jql(self) -> Optional[str]:
        """Get JQL query for syncing."""
        return self.data.get("sync", {}).get("jql")

    @property
    def sync_rate_limit(self) -> int:
        """Get API rate limit (requests per minute)."""
        return self.data.get("sync", {}).get("rate_limit", 100)

    @property
    def sync_batch_size(self) -> int:
        """Get sync batch size."""
        return self.data.get("sync", {}).get("batch_size", 100)

    @property
    def custom_fields(self) -> List[Dict[str, str]]:
        """Get custom fields configuration."""
        return self.data.get("custom_fields", [])

    @property
    def search_max_results(self) -> int:
        """Get maximum search results."""
        return self.data.get("search", {}).get("max_results", 1000)

    @property
    def search_timeout_seconds(self) -> int:
        """Get search timeout in seconds."""
        return self.data.get("search", {}).get("timeout_seconds", 5)

    @property
    def api_enable_rate_limiting(self) -> bool:
        """Get whether to enable web API rate limiting."""
        return self.data.get("api", {}).get("enable_rate_limiting", True)

    @property
    def database_path(self) -> str:
        """Get database file path."""
        return self.data.get("database", {}).get("path", "jira_search.db")

    @property
    def core_fields(self) -> List[str]:
        """Get list of core Jira fields to fetch and index."""
        default_fields = [
            "key",
            "summary",
            "description",
            "status",
            "priority",
            "assignee",
            "reporter",
            "created",
            "updated",
            "comment",
            "labels",
            "issuetype",
            "components",
        ]
        return self.data.get("fields", {}).get("core", default_fields)

    @property
    def search_fields(self) -> List[str]:
        """Get list of fields to include in full-text search index."""
        default_search_fields = ["key", "summary", "description", "comment", "labels"]
        return self.data.get("fields", {}).get("search", default_search_fields)

    def get_config_section(
        self, section: str, default: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get a configuration section with defaults."""
        return self.data.get(section, default or {})

    def get_setting(self, path: str, default: Any = None) -> Any:
        """Get a configuration setting using dot notation (e.g., 'sync.rate_limit')."""
        keys = path.split(".")
        value = self.data

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def update_custom_fields_from_jira(self, jira_client) -> List[Dict[str, str]]:
        """Discover and update custom fields from Jira API.

        Args:
            jira_client: JiraClient instance for API calls

        Returns:
            List of discovered custom fields
        """
        try:
            # Get all custom fields from Jira
            discovered_fields = jira_client.get_custom_fields()

            # Filter to commonly used fields and add to config
            relevant_fields = []
            for field in discovered_fields:
                field_id = field.get("id")
                field_name = field.get("name", "")
                field_type = self._map_jira_field_type(
                    field.get("schema", {}).get("type", "string")
                )

                # Include fields that might be useful for search/filtering
                if any(
                    keyword in field_name.lower()
                    for keyword in [
                        "team",
                        "component",
                        "epic",
                        "story",
                        "points",
                        "priority",
                        "severity",
                        "impact",
                        "environment",
                        "version",
                        "product",
                    ]
                ):
                    relevant_fields.append(
                        {
                            "id": field_id,
                            "name": field_name,
                            "type": field_type,
                            "discovered": True,  # Mark as auto-discovered
                        }
                    )

            return relevant_fields

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to discover custom fields from Jira: {e}")
            return []

    def _map_jira_field_type(self, jira_type: str) -> str:
        """Map Jira field types to our simplified types."""
        type_mapping = {
            "string": "text",
            "number": "number",
            "option": "select",
            "array": "multiselect",
            "date": "date",
            "datetime": "date",
            "user": "text",
            "group": "text",
            "project": "text",
            "version": "text",
        }
        return type_mapping.get(jira_type.lower(), "text")

    def generate_example_config(self) -> str:
        """Generate an example configuration with comments and documentation."""
        return """# Jira Search Configuration
# This file supports environment variable substitution using ${VAR_NAME} or ${VAR_NAME:default}

# Jira Connection Settings
jira:
  # Jira instance URL (required)
  url: "${JIRA_URL:https://your-jira.company.com}"

  # Jira username (required)
  username: "${JIRA_USERNAME:your-username}"

  # Personal Access Token (required)
  # Create one at: https://id.atlassian.com/manage-profile/security/api-tokens
  pat: "${JIRA_PAT}"

# Sync Configuration
sync:
  # Project key to sync (optional, use either this or jql)
  project_key: "${JIRA_PROJECT:}"

  # Custom JQL query for syncing (optional, use either this or project_key)
  # Example: "project = PROJ AND created >= -30d"
  jql: "${JIRA_SYNC_JQL:}"

  # API rate limiting (requests per minute, default: 100)
  rate_limit: 100

  # Batch size for syncing issues (default: 100)
  batch_size: 100

# Search Configuration
search:
  # Maximum search results to return (default: 1000)
  max_results: 1000

  # Search timeout in seconds (default: 5)
  timeout_seconds: 5

# Web API Configuration
api:
  # Enable rate limiting for web API endpoints (default: true)
  # Set to false to disable rate limiting for internal/trusted networks
  enable_rate_limiting: true

# Database Configuration
database:
  # Database file path (default: jira_search.db)
  path: "jira_search.db"

# Field Configuration
fields:
  # Core Jira fields to fetch and store (required: key, summary)
  core:
    - "key"
    - "summary"
    - "description"
    - "status"
    - "priority"
    - "assignee"
    - "reporter"
    - "created"
    - "updated"
    - "comment"
    - "labels"           # New: Issue labels/tags
    - "components"       # Optional: Project components
    - "fixVersions"      # Optional: Fix versions
    - "affectedVersions" # Optional: Affected versions

  # Fields to include in full-text search index (subset of core)
  search:
    - "key"
    - "summary"
    - "description"
    - "comment"
    - "labels"

# Custom Fields Configuration
# Add any custom fields you want to include in search and display
custom_fields:
  - id: "customfield_10001"
    name: "Story Points"
    type: "number"

  - id: "customfield_10002"
    name: "Epic Link"
    type: "text"

  - id: "customfield_10003"
    name: "Team"
    type: "select"

  - id: "customfield_10004"
    name: "Sprint"
    type: "multiselect"

# Performance Tuning (optional)
performance:
  # Enable query caching (default: true)
  cache_queries: true

  # Cache TTL in seconds (default: 300)
  cache_ttl: 300

  # Database connection pool size (default: 5)
  db_pool_size: 5

# Logging Configuration (optional)
logging:
  # Log level (DEBUG, INFO, WARNING, ERROR, default: INFO)
  level: "INFO"

  # Log file path (optional, logs to console if not specified)
  file: "jira_search.log"

  # Enable structured logging (default: false)
  structured: false
"""


def load_config(config_path: Optional[str] = None) -> Config:
    """Load and validate configuration.

    Args:
        config_path: Path to config.yaml file

    Returns:
        Loaded and validated configuration

    Raises:
        ConfigError: If configuration is invalid or missing
    """
    return Config(config_path)
