"""Pytest configuration and fixtures."""

import os
import shutil
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment before running tests."""
    # Set required environment variables for testing if not already set
    test_env_vars = {
        'JIRA_URL': 'https://test-jira.example.com',
        'JIRA_USERNAME': 'test-user',
        'JIRA_PAT': 'test-token'
    }
    
    for var, value in test_env_vars.items():
        if var not in os.environ:
            os.environ[var] = value
    
    # Copy config.yaml.example to config.yaml if it doesn't exist
    config_example = Path("config.yaml.example")
    config_file = Path("config.yaml")
    
    if config_example.exists() and not config_file.exists():
        shutil.copy2(config_example, config_file)
        print(f"Copied {config_example} to {config_file} for testing")
    
    yield
    
    # Cleanup: Remove the copied config file if we created it
    # (Only remove if it's identical to the example - safety check)
    if config_file.exists() and config_example.exists():
        try:
            if config_file.read_text() == config_example.read_text():
                config_file.unlink()
                print(f"Cleaned up test config file: {config_file}")
        except Exception:
            # If cleanup fails, leave the file (better safe than sorry)
            pass