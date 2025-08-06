"""Command-line interface for Jira Search Mirror."""

import click
import logging
import sqlite3
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
        
        # Perform actual sync with timing and statistics
        import time
        sync_start_time = time.time()
        
        click.echo(f"Starting sync of {total_issues} issues...")
        synced_count = 0
        added_count = 0
        updated_count = 0
        error_count = 0
        
        with click.progressbar(length=total_issues, label='Syncing issues') as bar:
            for issue in client.search_issues_paginated(sync_jql):
                try:
                    # Check if issue exists to track add vs update
                    issue_key = issue.get('key')
                    with sqlite3.connect(db.db_path) as conn:
                        cursor = conn.execute("SELECT key FROM issues WHERE key = ?", (issue_key,))
                        existing = cursor.fetchone()
                    
                    db.upsert_issue(issue)
                    synced_count += 1
                    
                    if existing:
                        updated_count += 1
                    else:
                        added_count += 1
                    
                    bar.update(1)
                except Exception as e:
                    logger.warning(f"Failed to sync issue {issue.get('key', 'unknown')}: {e}")
                    error_count += 1
                    bar.update(1)  # Still update progress even on error
        
        sync_duration = time.time() - sync_start_time
        
        click.echo(f"✓ Sync completed in {sync_duration:.1f} seconds:")
        click.echo(f"  • {synced_count}/{total_issues} issues processed")
        click.echo(f"  • {added_count} issues added")
        click.echo(f"  • {updated_count} issues updated")
        if error_count > 0:
            click.echo(f"  • {error_count} errors encountered")
        
        # Update sync metadata with statistics
        sync_stats = {
            'processed': synced_count,
            'added': added_count,
            'updated': updated_count,
            'deleted': 0  # TODO: Implement deletion detection in future enhancement
        }
        db.update_sync_metadata(sync_jql, is_full_sync=full, sync_stats=sync_stats, 
                              duration_seconds=sync_duration)
        
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
@click.option('--format', default='csv', type=click.Choice(['csv', 'json'], case_sensitive=False), 
              help='Export format (csv or json)')
@click.option('--output', '-o', help='Output file path (default: stdout)')
@click.option('--query', help='JQL query to filter exported issues')
@click.option('--include-deleted', is_flag=True, help='Include deleted issues in export')
@click.pass_context
def export(ctx, format: str, output: Optional[str], query: Optional[str], include_deleted: bool):
    """Export issues to CSV or JSON format."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not db.exists():
            click.echo("Database not initialized. Run 'sync' command first.", err=True)
            sys.exit(1)
        
        # Build export query
        if query:
            # Use custom query if provided
            export_query = query
        else:
            # Export all issues
            export_query = "*"
        
        import csv
        import json
        
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Build WHERE clause
            where_clause = ""
            if not include_deleted:
                where_clause = "WHERE (is_deleted IS NULL OR is_deleted = FALSE)"
            
            # Get issues
            if query and query != "*":
                # Use FTS search for complex queries
                if include_deleted:
                    sql = """
                        SELECT i.* FROM issues_fts fts
                        JOIN issues i ON i.rowid = fts.rowid
                        WHERE issues_fts MATCH ?
                        ORDER BY i.updated DESC
                    """
                    params = (query,)
                else:
                    sql = """
                        SELECT i.* FROM issues_fts fts
                        JOIN issues i ON i.rowid = fts.rowid
                        WHERE issues_fts MATCH ? AND (i.is_deleted IS NULL OR i.is_deleted = FALSE)
                        ORDER BY i.updated DESC
                    """
                    params = (query,)
            else:
                # Export all issues
                sql = f"SELECT * FROM issues {where_clause} ORDER BY updated DESC"
                params = ()
            
            cursor = conn.execute(sql, params)
            issues = [dict(row) for row in cursor.fetchall()]
        
        if not issues:
            click.echo("No issues found for export.")
            return
        
        click.echo(f"Exporting {len(issues)} issues in {format.upper()} format...")
        
        # Handle output destination
        if output:
            output_file = open(output, 'w', newline='', encoding='utf-8')
        else:
            output_file = sys.stdout
        
        try:
            if format.lower() == 'csv':
                # Export as CSV
                if issues:
                    fieldnames = issues[0].keys()
                    writer = csv.DictWriter(output_file, fieldnames=fieldnames)
                    writer.writeheader()
                    for issue in issues:
                        # Handle None values and convert to strings
                        clean_issue = {k: str(v) if v is not None else '' for k, v in issue.items()}
                        writer.writerow(clean_issue)
            
            elif format.lower() == 'json':
                # Export as JSON
                json.dump(issues, output_file, indent=2, default=str)
            
            if output:
                click.echo(f"✓ Export completed: {output}")
            
        finally:
            if output:
                output_file.close()
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except DatabaseError as e:
        click.echo(f"✗ Database error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Export failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--days', default=30, help='Remove issues deleted more than N days ago')
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.pass_context
def cleanup(ctx, days: int, dry_run: bool):
    """Clean up old deleted issues from the database."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not db.exists():
            click.echo("Database not initialized. Run 'sync' command first.", err=True)
            sys.exit(1)
        
        if dry_run:
            # Count issues that would be deleted
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            with sqlite3.connect(db.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM issues 
                    WHERE is_deleted = TRUE AND deleted_at < ?
                """, (cutoff_date,))
                count = cursor.fetchone()[0]
            
            click.echo(f"DRY RUN - Would remove {count} issues deleted more than {days} days ago")
            return
        
        # Perform cleanup
        count = db.cleanup_deleted_issues(days)
        click.echo(f"✓ Cleaned up {count} old deleted issues (older than {days} days)")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except DatabaseError as e:
        click.echo(f"✗ Database error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Cleanup failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--output', '-o', required=True, help='Backup file path (.db extension recommended)')
@click.pass_context
def backup(ctx, output: str):
    """Create a backup of the database."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not db.exists():
            click.echo("Database not initialized. Run 'sync' command first.", err=True)
            sys.exit(1)
        
        import shutil
        shutil.copy2(db.db_path, output)
        
        # Get file size for confirmation
        import os
        size_mb = os.path.getsize(output) / (1024 * 1024)
        
        click.echo(f"✓ Database backup created: {output} ({size_mb:.1f} MB)")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Backup failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--input', '-i', required=True, help='Backup file path to restore from')
@click.option('--force', is_flag=True, help='Overwrite existing database without confirmation')
@click.pass_context
def restore(ctx, input: str, force: bool):
    """Restore database from a backup file."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if not Path(input).exists():
            click.echo(f"Backup file not found: {input}", err=True)
            sys.exit(1)
        
        if db.exists() and not force:
            click.echo("Database already exists. Use --force to overwrite.")
            if not click.confirm("Continue with restore?"):
                return
        
        import shutil
        shutil.copy2(input, db.db_path)
        
        # Verify restored database
        try:
            stats = db.get_statistics()
            click.echo(f"✓ Database restored from: {input}")
            click.echo(f"  • {stats['total_issues']} issues restored")
            click.echo(f"  • Database size: {stats['database_size_mb']:.1f} MB")
        except Exception as e:
            click.echo(f"⚠️  Database restored but verification failed: {e}")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Restore failed: {e}", err=True)
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
        
        click.echo("📊 Database Statistics:")
        click.echo(f"  Total issues: {stats['total_issues']}")
        click.echo(f"  Database size: {stats['database_size_mb']:.1f} MB")
        
        if stats['oldest_issue']:
            click.echo(f"  Oldest issue: {stats['oldest_issue']}")
        if stats['newest_issue']:
            click.echo(f"  Newest issue: {stats['newest_issue']}")
        
        click.echo()
        click.echo("🔄 Sync Information:")
        click.echo(f"  Last sync: {stats['last_sync_time'] or 'Never'}")
        click.echo(f"  Last full sync: {stats.get('last_full_sync', 'Never')}")
        click.echo(f"  Last sync query: {stats['last_sync_query'] or 'Unknown'}")
        
        if stats.get('sync_duration_seconds'):
            duration = stats['sync_duration_seconds']
            if duration < 60:
                duration_str = f"{duration:.1f} seconds"
            else:
                duration_str = f"{duration/60:.1f} minutes"
            click.echo(f"  Last sync duration: {duration_str}")
        
        if stats.get('issues_processed'):
            click.echo()
            click.echo("📈 Last Sync Stats:")
            click.echo(f"  Issues processed: {stats.get('issues_processed', 0)}")
            click.echo(f"  Issues added: {stats.get('issues_added', 0)}")
            click.echo(f"  Issues updated: {stats.get('issues_updated', 0)}")
            click.echo(f"  Issues deleted: {stats.get('issues_deleted', 0)}")
        
        # Show deleted issues count
        deleted_issues = db.get_deleted_issues(limit=1)
        if deleted_issues:
            total_deleted = len(db.get_deleted_issues(limit=1000))  # Get rough count
            click.echo()
            click.echo("🗑️  Deleted Issues:")
            click.echo(f"  Recently deleted: {total_deleted} issues")
            click.echo(f"  Most recent: {deleted_issues[0]['key']} at {deleted_issues[0]['deleted_at'][:19]}")
        
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