"""WSGI entry point for Gunicorn production deployment."""

import os
import logging
from jira_search.config import load_config
from jira_search.web import create_app

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def create_application():
    """Create Flask application for WSGI deployment.
    
    Returns:
        Flask application instance
    """
    try:
        # Load configuration
        config_path = os.environ.get('CONFIG_PATH', '/app/config.yaml')
        if os.path.exists(config_path):
            config = load_config(config_path)
            logger.info(f"Loaded configuration from {config_path}")
        else:
            # Fallback to default config path
            config = load_config('config.yaml')
            logger.info("Loaded configuration from config.yaml")
        
        # Create Flask application
        app = create_app(config)
        logger.info("Flask application created successfully")
        
        return app
        
    except Exception as e:
        logger.error(f"Failed to create application: {e}")
        raise

# Create application instance for Gunicorn
application = create_application()

if __name__ == "__main__":
    # For local testing with python -m jira_search.wsgi
    application.run(host='0.0.0.0', port=8080, debug=False)