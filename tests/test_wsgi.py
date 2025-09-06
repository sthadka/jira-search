"""Tests for WSGI module."""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock

from jira_search.wsgi import create_application


class TestWSGI:
    """Test WSGI application creation."""
    
    def test_create_application_with_valid_config(self):
        """Test WSGI application creation with valid configuration."""
        config_content = """
jira:
  url: "https://test-jira.example.com"
  username: "test-user"
  pat: "test-token"

sync:
  project_key: "TEST"

search:
  max_results: 1000
  timeout_seconds: 5

database:
  path: "/tmp/test.db"

custom_fields: []
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_content)
            f.flush()
            
            try:
                # Set CONFIG_PATH environment variable
                os.environ['CONFIG_PATH'] = f.name
                
                # Mock the database to avoid actual database operations
                with patch('jira_search.web.Database') as mock_db:
                    mock_db.return_value = MagicMock()
                    app = create_application()
                    assert app is not None
                    assert hasattr(app, 'config')
                    
            finally:
                os.unlink(f.name)
                if 'CONFIG_PATH' in os.environ:
                    del os.environ['CONFIG_PATH']
    
    def test_create_application_fallback_config(self):
        """Test WSGI application creation with fallback config path."""
        # Create a temporary config.yaml in current directory
        config_content = """
jira:
  url: "https://test-jira.example.com"
  username: "test-user"
  pat: "test-token"

sync:
  project_key: "TEST"

custom_fields: []
"""
        
        # Remove CONFIG_PATH if it exists
        if 'CONFIG_PATH' in os.environ:
            del os.environ['CONFIG_PATH']
            
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, 
                                       dir='.', prefix='config') as f:
            f.write(config_content)
            f.flush()
            config_filename = os.path.basename(f.name)
            
            try:
                # Mock the database and config loading
                with patch('jira_search.wsgi.load_config') as mock_load_config, \
                     patch('jira_search.web.Database') as mock_db:
                    
                    mock_config = MagicMock()
                    mock_load_config.return_value = mock_config
                    mock_db.return_value = MagicMock()
                    
                    app = create_application()
                    assert app is not None
                    
                    # Verify it tried to load config.yaml as fallback
                    mock_load_config.assert_called()
                    
            finally:
                os.unlink(f.name)
    
    def test_application_instance_exists(self):
        """Test that the application instance is created."""
        # Mock everything to avoid dependencies
        with patch('jira_search.wsgi.load_config') as mock_load_config, \
             patch('jira_search.web.create_app') as mock_create_app:
            
            mock_config = MagicMock()
            mock_app = MagicMock()
            mock_load_config.return_value = mock_config
            mock_create_app.return_value = mock_app
            
            # Import the application instance
            from jira_search.wsgi import application
            assert application is not None