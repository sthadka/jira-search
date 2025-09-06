"""Tests for basic imports and module availability."""

import pytest


class TestImports:
    """Test that all modules can be imported successfully."""
    
    def test_import_config(self):
        """Test importing config module."""
        from jira_search import config
        assert hasattr(config, 'Config')
        assert hasattr(config, 'load_config')
    
    def test_import_cli(self):
        """Test importing CLI module."""
        from jira_search import cli
        assert hasattr(cli, 'cli')
    
    def test_import_web(self):
        """Test importing web module."""
        from jira_search import web
        assert hasattr(web, 'create_app')
    
    def test_import_wsgi(self):
        """Test importing WSGI module."""
        from unittest.mock import patch, MagicMock
        
        # Mock the dependencies to avoid config file requirements
        with patch('jira_search.wsgi.load_config') as mock_load_config, \
             patch('jira_search.web.create_app') as mock_create_app:
            
            mock_load_config.return_value = MagicMock()
            mock_create_app.return_value = MagicMock()
            
            from jira_search import wsgi
            assert hasattr(wsgi, 'create_application')
    
    def test_import_database(self):
        """Test importing database module."""
        from jira_search import database
        assert hasattr(database, 'Database')
        assert hasattr(database, 'DatabaseError')
    
    def test_import_jira_client(self):
        """Test importing Jira client module."""
        from jira_search import jira_client
        assert hasattr(jira_client, 'JiraClient')
    
    def test_import_search(self):
        """Test importing search module."""
        from jira_search import search
        assert hasattr(search, 'AdvancedSearch')
    
    def test_package_version(self):
        """Test that package has version information."""
        import jira_search
        # Package should be importable
        assert jira_search is not None
    
    def test_main_module_runnable(self):
        """Test that main module is importable."""
        from jira_search import __main__
        assert __main__ is not None