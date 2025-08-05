"""Configuration management for Jira Search Mirror."""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any


class ConfigError(Exception):
    """Configuration-related errors."""
    pass


class Config:
    """Configuration manager for Jira Search Mirror."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration.
        
        Args:
            config_path: Path to config.yaml file. Defaults to './config.yaml'
        """
        self.config_path = config_path or "config.yaml"
        self.data = {}
        self.load()
    
    def load(self) -> None:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            raise ConfigError(
                f"Configuration file not found: {self.config_path}\n"
                f"Copy config.yaml.example to {self.config_path} and update with your details."
            )
        
        try:
            with open(self.config_path, 'r') as f:
                self.data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to read config file: {e}")
        
        self.validate()
    
    def validate(self) -> None:
        """Validate required configuration values."""
        errors = []
        
        # Jira configuration
        jira_config = self.data.get('jira', {})
        if not jira_config.get('url'):
            errors.append("jira.url is required")
        if not jira_config.get('username'):
            errors.append("jira.username is required")
        if not jira_config.get('pat'):
            errors.append("jira.pat (Personal Access Token) is required")
        
        # Sync configuration
        sync_config = self.data.get('sync', {})
        project_key = sync_config.get('project_key')
        jql = sync_config.get('jql')
        if not project_key and not jql:
            errors.append("Either sync.project_key or sync.jql must be specified")
        
        if errors:
            raise ConfigError("Configuration validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    
    @property
    def jira_url(self) -> str:
        """Get Jira base URL."""
        return self.data['jira']['url'].rstrip('/')
    
    @property
    def jira_username(self) -> str:
        """Get Jira username."""
        return self.data['jira']['username']
    
    @property
    def jira_pat(self) -> str:
        """Get Jira Personal Access Token."""
        return self.data['jira']['pat']
    
    @property
    def sync_project_key(self) -> Optional[str]:
        """Get project key for syncing."""
        return self.data.get('sync', {}).get('project_key')
    
    @property
    def sync_jql(self) -> Optional[str]:
        """Get JQL query for syncing."""
        return self.data.get('sync', {}).get('jql')
    
    @property
    def sync_rate_limit(self) -> int:
        """Get API rate limit (requests per minute)."""
        return self.data.get('sync', {}).get('rate_limit', 100)
    
    @property
    def sync_batch_size(self) -> int:
        """Get sync batch size."""
        return self.data.get('sync', {}).get('batch_size', 100)
    
    @property
    def custom_fields(self) -> List[Dict[str, str]]:
        """Get custom fields configuration."""
        return self.data.get('custom_fields', [])
    
    @property
    def search_max_results(self) -> int:
        """Get maximum search results."""
        return self.data.get('search', {}).get('max_results', 1000)
    
    @property
    def search_timeout_seconds(self) -> int:
        """Get search timeout in seconds."""
        return self.data.get('search', {}).get('timeout_seconds', 5)
    
    @property
    def database_path(self) -> str:
        """Get database file path."""
        return self.data.get('database', {}).get('path', 'jira_search.db')


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