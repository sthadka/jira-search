"""Pytest configuration and fixtures."""

import os
import shutil
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment before running tests."""
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