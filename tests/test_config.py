"""Tests for configuration module."""

import pytest
import tempfile
import os
from pathlib import Path

from jira_search.config import Config, ConfigError, load_config


class TestConfig:
    """Test configuration loading and validation."""
    
    def test_config_creation(self):
        """Test basic config object creation."""
        # Since we now have conftest.py that creates config.yaml, we can load it
        config = Config()
        
        # Test that config object has expected attributes
        assert hasattr(config, 'jira_url')
        assert hasattr(config, 'jira_username') 
        assert hasattr(config, 'database_path')
        
        # Test that properties are accessible
        assert config.jira_url is not None
        assert config.jira_username is not None
        assert config.database_path is not None
    
    def test_load_valid_config(self):
        """Test loading a valid configuration file."""
        config_content = """
jira:
  url: "https://test-jira.example.com"
  username: "test-user"
  pat: "test-token"

sync:
  project_key: "TEST"
  rate_limit: 100
  batch_size: 50

search:
  max_results: 500
  timeout_seconds: 10

database:
  path: "/tmp/test.db"

custom_fields: []
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_content)
            f.flush()
            
            try:
                config = load_config(f.name)
                assert config.jira_url == "https://test-jira.example.com"
                assert config.jira_username == "test-user"
                assert config.sync_project_key == "TEST"
                assert config.sync_rate_limit == 100
                assert config.search_max_results == 500
            finally:
                os.unlink(f.name)
    
    def test_load_missing_config_file(self):
        """Test loading a non-existent configuration file."""
        with pytest.raises(ConfigError):
            load_config("/nonexistent/config.yaml")
    
    def test_config_with_environment_variables(self):
        """Test configuration with environment variable substitution."""
        config_content = """
jira:
  url: "${TEST_JIRA_URL:https://default-jira.example.com}"
  username: "${TEST_USERNAME}"
  pat: "${TEST_PAT}"

sync:
  project_key: "TEST"

custom_fields: []
"""
        # Set environment variables
        os.environ['TEST_JIRA_URL'] = 'https://env-jira.example.com'
        os.environ['TEST_USERNAME'] = 'env-user'
        os.environ['TEST_PAT'] = 'env-token'
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_content)
            f.flush()
            
            try:
                config = load_config(f.name)
                assert config.jira_url == "https://env-jira.example.com"
                assert config.jira_username == "env-user"
            finally:
                os.unlink(f.name)
                # Clean up environment variables
                del os.environ['TEST_JIRA_URL']
                del os.environ['TEST_USERNAME']
                del os.environ['TEST_PAT']
    
    def test_invalid_yaml_config(self):
        """Test loading invalid YAML configuration."""
        invalid_config = """
jira:
  url: "https://test-jira.example.com"
  username: "test-user"
  pat: "test-token"
    invalid_indentation: "value"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_config)
            f.flush()
            
            try:
                with pytest.raises(ConfigError):
                    load_config(f.name)
            finally:
                os.unlink(f.name)