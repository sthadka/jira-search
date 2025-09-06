"""Tests for WSGI module."""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock


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
                
                # Import and use the function
                from jira_search.wsgi import create_application
                
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
    
    @patch('jira_search.wsgi.load_config')
    @patch('jira_search.web.Database')
    def test_create_application_fallback_config(self, mock_db, mock_load_config):
        """Test WSGI application creation with fallback config path."""
        # Remove CONFIG_PATH if it exists
        if 'CONFIG_PATH' in os.environ:
            del os.environ['CONFIG_PATH']
            
        # Mock the config loading and database
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_db.return_value = MagicMock()
        
        # Import and use the function
        from jira_search.wsgi import create_application
        
        app = create_application()
        assert app is not None
        
        # Verify it tried to load config.yaml as fallback
        mock_load_config.assert_called()
    
    @patch('jira_search.wsgi.load_config')
    @patch('jira_search.web.create_app')  
    def test_wsgi_module_importable(self, mock_create_app, mock_load_config):
        """Test that the WSGI module can be imported without errors."""
        # Mock everything to avoid dependencies
        mock_config = MagicMock()
        mock_app = MagicMock()
        mock_load_config.return_value = mock_config
        mock_create_app.return_value = mock_app
        
        # Test that we can import the module functions
        try:
            from jira_search.wsgi import create_application
            assert create_application is not None
        except ImportError:
            pytest.fail("Could not import WSGI module")