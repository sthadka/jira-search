"""Command-line interface for Jira Search Mirror."""

import click
import logging
import sys
from pathlib import Path
from typing import Optional

from jira_search.config import Config, ConfigError, load_config
from jira_search.jira_client import JiraClient, JiraClientError
from jira_search.database import Database, DatabaseError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
@click.option('--config', '-c', default='config.yaml', help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, config: str, verbose: bool):
    """Jira Search Mirror - Fast local search for Jira issues."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config


@cli.command()
@click.pass_context
def init_config(ctx):
    """Generate a sample configuration file."""
    config_path = ctx.obj['config_path']
    example_path = 'config.yaml.example'
    
    if Path(config_path).exists():
        click.echo(f"Configuration file {config_path} already exists.")
        if not click.confirm("Overwrite existing file?"):
            return
    
    if not Path(example_path).exists():
        click.echo(f"Error: {example_path} not found in current directory.", err=True)
        click.echo("Please run this command from the jira-search project directory.", err=True)
        sys.exit(1)
    
    try:
        # Copy example file to config file
        with open(example_path, 'r') as src:
            content = src.read()
        
        with open(config_path, 'w') as dst:
            dst.write(content)
        
        click.echo(f"Configuration template created: {config_path}")
        click.echo("Please edit the file with your Jira details before running other commands.")
        
    except Exception as e:
        click.echo(f"Error creating configuration file: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def validate_config(ctx):
    """Validate configuration file."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        click.echo("✓ Configuration file is valid")
        
        # Show configuration summary
        click.echo(f"  Jira URL: {config.jira_url}")
        click.echo(f"  Username: {config.jira_username}")
        click.echo(f"  Database: {config.database_path}")
        
        if config.sync_project_key:
            click.echo(f"  Sync scope: Project {config.sync_project_key}")
        elif config.sync_jql:
            click.echo(f"  Sync scope: JQL query")
        
        if config.custom_fields:
            click.echo(f"  Custom fields: {len(config.custom_fields)} configured")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration validation failed:", err=True)
        click.echo(f"  {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Error loading configuration: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def test_connection(ctx):
    """Test connection to Jira."""
    config_path = ctx.obj['config_path']
    
    try:
        # Load and validate config
        config = load_config(config_path)
        click.echo("✓ Configuration loaded successfully")
        
        # Test Jira connection
        client = JiraClient(config)
        result = client.test_connection()
        
        if result['success']:
            click.echo("✓ Successfully connected to Jira")
            click.echo(f"  User: {result['user']} ({result['username']})")
            if result.get('email'):
                click.echo(f"  Email: {result['email']}")
            click.echo(f"  Jira version: {result['jira_version']}")
        else:
            click.echo("✗ Connection failed:", err=True)
            click.echo(f"  {result['error']}", err=True)
            sys.exit(1)
            
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except JiraClientError as e:
        click.echo(f"✗ Jira connection error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--project', help='Project key to sync (e.g., PROJ)')
@click.option('--jql', help='JQL query to sync')
@click.option('--incremental', is_flag=True, help='Perform incremental sync')
@click.option('--full', is_flag=True, help='Force full re-sync')
@click.option('--dry-run', is_flag=True, help='Show what would be synced without making changes')
@click.pass_context
def sync(ctx, project: Optional[str], jql: Optional[str], incremental: bool, full: bool, dry_run: bool):
    """Sync issues from Jira to local database."""
    config_path = ctx.obj['config_path']
    
    try:
        # Load config
        config = load_config(config_path)
        
        # Initialize database
        db = Database(config)
        db.initialize()
        
        # Determine base sync query
        if jql:
            base_sync_jql = jql
        elif project:
            base_sync_jql = f"project = {project}"
        elif config.sync_jql:
            base_sync_jql = config.sync_jql
        elif config.sync_project_key:
            base_sync_jql = f"project = {config.sync_project_key}"
        else:
            click.echo("Error: No sync query specified. Use --project, --jql, or configure in config.yaml", err=True)
            sys.exit(1)
        
        # Handle incremental sync
        sync_jql = base_sync_jql
        if incremental and not full:
            last_sync_time = db.get_last_sync_time()
            if last_sync_time:
                # Convert ISO timestamp to JQL-compatible format (remove microseconds)
                from datetime import datetime
                dt = datetime.fromisoformat(last_sync_time.replace('Z', '+00:00'))
                jql_timestamp = dt.strftime('%Y-%m-%d %H:%M')
                
                # Add incremental filter to JQL
                sync_jql = f"({base_sync_jql}) AND updated >= '{jql_timestamp}'"
                click.echo(f"Incremental sync from: {jql_timestamp}")
            else:
                click.echo("No previous sync found, performing full sync")
                incremental = False
        
        click.echo(f"Sync query: {sync_jql}")
        
        if dry_run:
            click.echo("DRY RUN - No changes will be made")
        
        if full and not dry_run:
            click.echo("Performing full re-sync (clearing existing data)")
            db.clear_issues()
        
        # Test Jira connection
        client = JiraClient(config)
        connection_result = client.test_connection()
        
        if not connection_result['success']:
            click.echo(f"✗ Jira connection failed: {connection_result['error']}", err=True)
            sys.exit(1)
        
        click.echo("✓ Connected to Jira")
        
        # Validate JQL
        if not client.validate_jql(sync_jql):
            click.echo(f"✗ Invalid JQL query: {sync_jql}", err=True)
            sys.exit(1)
        
        click.echo("✓ JQL query is valid")
        
        if dry_run:
            # Just count issues for dry run
            result = client.search_issues(sync_jql, max_results=0)
            total_issues = result.get('total', 0)
            click.echo(f"Would sync {total_issues} issues")
            return
        
        # Get total count for progress tracking
        click.echo("Counting issues to sync...")
        count_result = client.search_issues(sync_jql, max_results=0)
        total_issues = count_result.get('total', 0)
        
        if total_issues == 0:
            click.echo("No issues found matching the sync query")
            return
        
        # Perform actual sync
        click.echo(f"Starting sync of {total_issues} issues...")
        synced_count = 0
        
        with click.progressbar(length=total_issues, label='Syncing issues') as bar:
            for issue in client.search_issues_paginated(sync_jql):
                try:
                    db.upsert_issue(issue)
                    synced_count += 1
                    bar.update(1)
                except Exception as e:
                    logger.warning(f"Failed to sync issue {issue.get('key', 'unknown')}: {e}")
                    bar.update(1)  # Still update progress even on error
        
        click.echo(f"✓ Sync completed: {synced_count}/{total_issues} issues processed")
        
        # Update last sync timestamp
        db.update_sync_metadata(sync_jql)
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except (JiraClientError, DatabaseError) as e:
        click.echo(f"✗ Sync failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during sync")
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """Show sync status and database statistics."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not db.exists():
            click.echo("Database not initialized. Run 'sync' command first.")
            return
        
        stats = db.get_statistics()
        
        click.echo("Database Statistics:")
        click.echo(f"  Total issues: {stats['total_issues']}")
        click.echo(f"  Last sync: {stats['last_sync_time'] or 'Never'}")
        click.echo(f"  Last sync query: {stats['last_sync_query'] or 'Unknown'}")
        click.echo(f"  Database size: {stats['database_size_mb']:.1f} MB")
        
        if stats['oldest_issue']:
            click.echo(f"  Oldest issue: {stats['oldest_issue']}")
        if stats['newest_issue']:
            click.echo(f"  Newest issue: {stats['newest_issue']}")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except DatabaseError as e:
        click.echo(f"✗ Database error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--port', default=8080, help='Port to run the web server on')
@click.option('--host', default='127.0.0.1', help='Host to bind the web server to')
@click.pass_context
def serve(ctx, port: int, host: str):
    """Start the web interface."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not db.exists():
            click.echo("Database not initialized. Run 'sync' command first.", err=True)
            sys.exit(1)
        
        # Import and start web server
        from jira_search.web import create_app
        app = create_app(config)
        
        click.echo(f"Starting web server at http://{host}:{port}")
        app.run(host=host, port=port, debug=False)
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except ImportError:
        click.echo("✗ Web server dependencies not available", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Failed to start web server: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point for CLI."""
    cli()