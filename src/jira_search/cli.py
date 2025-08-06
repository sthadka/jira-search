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
@click.option('--with-examples', is_flag=True, help='Include detailed examples and comments')
@click.option('--minimal', is_flag=True, help='Generate minimal configuration with required fields only')
@click.pass_context
def init_config(ctx, with_examples: bool, minimal: bool):
    """Generate a configuration file template."""
    config_path = ctx.obj['config_path']
    
    if Path(config_path).exists():
        click.echo(f"Configuration file {config_path} already exists.")
        if not click.confirm("Overwrite existing file?"):
            return
    
    try:
        if minimal:
            # Generate minimal config
            content = """# Minimal Jira Search Mirror Configuration
jira:
  url: "https://your-jira.company.com"
  username: "your-username"
  pat: "your-personal-access-token"

sync:
  project_key: "PROJ"  # or use 'jql' instead

custom_fields: []
"""
        else:
            # Generate full config with examples
            config = Config.__new__(Config)  # Create without loading
            content = config.generate_example_config()
        
        with open(config_path, 'w') as f:
            f.write(content)
        
        click.echo(f"✓ Configuration template created: {config_path}")
        if not minimal:
            click.echo("📝 The configuration includes:")
            click.echo("  • Environment variable support (${VAR_NAME} or ${VAR_NAME:default})")
            click.echo("  • Detailed comments and examples")
            click.echo("  • All available configuration options")
        click.echo()
        click.echo("Next steps:")
        click.echo("1. Edit the configuration file with your Jira details")
        click.echo("2. Test the connection: python -m jira_search test-connection")
        click.echo("3. Discover custom fields: python -m jira_search discover-fields")
        
    except Exception as e:
        click.echo(f"✗ Error creating configuration file: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--detailed', is_flag=True, help='Show detailed validation information')
@click.pass_context
def validate_config(ctx, detailed: bool):
    """Validate configuration file with comprehensive checks."""
    config_path = ctx.obj['config_path']
    
    try:
        click.echo("🔍 Validating configuration...")
        config = load_config(config_path)
        click.echo("✓ Configuration file is valid")
        
        if detailed:
            click.echo()
            click.echo("📋 Configuration Summary:")
            click.echo(f"  • Jira URL: {config.jira_url}")
            click.echo(f"  • Username: {config.jira_username}")
            click.echo(f"  • Database: {config.database_path}")
            click.echo(f"  • Rate limit: {config.sync_rate_limit} requests/minute")
            click.echo(f"  • Batch size: {config.sync_batch_size} issues/batch")
            click.echo(f"  • Search timeout: {config.search_timeout_seconds}s")
            click.echo(f"  • Max results: {config.search_max_results}")
            
            if config.sync_project_key:
                click.echo(f"  • Sync scope: Project {config.sync_project_key}")
            elif config.sync_jql:
                click.echo(f"  • Sync scope: Custom JQL query")
            
            if config.custom_fields:
                click.echo(f"  • Custom fields: {len(config.custom_fields)} configured")
                for field in config.custom_fields:
                    click.echo(f"    - {field.get('name', 'Unnamed')} ({field.get('id')}) [{field.get('type', 'text')}]")
            else:
                click.echo(f"  • Custom fields: None configured")
            
            # Check environment variables used
            env_vars_used = []
            try:
                with open(config_path, 'r') as f:
                    content = f.read()
                    import re
                    env_vars = re.findall(r'\$\{([^}]+)\}', content)
                    for var in env_vars:
                        var_name = var.split(':')[0] if ':' in var else var
                        env_vars_used.append(var_name)
                
                if env_vars_used:
                    click.echo(f"  • Environment variables: {', '.join(set(env_vars_used))}")
            except Exception:
                pass
        
        click.echo()
        click.echo("✅ Configuration is ready for use!")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration validation failed:", err=True)
        click.echo()
        # Split error message into lines and format nicely
        error_lines = str(e).split('\n')
        for line in error_lines:
            if line.strip():
                click.echo(f"  {line}", err=True)
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


@cli.command('discover-fields')
@click.option('--project', help='Project key to filter fields (optional)')
@click.option('--output', help='Output discovered fields to config file section')
@click.option('--filter', help='Filter fields by name (case-insensitive substring match)')
@click.pass_context
def discover_fields(ctx, project: Optional[str], output: Optional[str], filter: Optional[str]):
    """Discover custom fields from Jira and optionally update configuration."""
    config_path = ctx.obj['config_path']
    
    try:
        # Load config and test connection
        config = load_config(config_path)
        client = JiraClient(config)
        
        click.echo("🔍 Discovering custom fields from Jira...")
        
        # Test connection first
        connection_result = client.test_connection()
        if not connection_result['success']:
            click.echo(f"✗ Jira connection failed: {connection_result['error']}", err=True)
            sys.exit(1)
        
        # Get custom fields
        if project:
            click.echo(f"📁 Getting custom fields for project: {project}")
            custom_fields = client.get_project_custom_fields(project)
        else:
            click.echo("🌐 Getting all custom fields from Jira...")
            custom_fields = client.get_custom_fields()
        
        # Apply filter if specified
        if filter:
            filter_lower = filter.lower()
            custom_fields = [
                field for field in custom_fields
                if filter_lower in field.get('name', '').lower()
            ]
            click.echo(f"🔍 Filtered to {len(custom_fields)} fields matching '{filter}'")
        
        if not custom_fields:
            click.echo("No custom fields found.")
            return
        
        click.echo(f"✓ Found {len(custom_fields)} custom fields:")
        click.echo()
        
        # Display discovered fields
        relevant_fields = []
        for field in custom_fields:
            field_id = field.get('id')
            field_name = field.get('name', 'Unnamed')
            field_type = field.get('schema', {}).get('type', 'string')
            
            # Check if field might be useful for search/filtering
            is_relevant = any(keyword in field_name.lower() for keyword in [
                'team', 'component', 'epic', 'story', 'points', 'priority', 
                'severity', 'impact', 'environment', 'version', 'product',
                'sprint', 'fixversion', 'affectedversion', 'label'
            ])
            
            status_icon = "⭐" if is_relevant else "  "
            click.echo(f"{status_icon} {field_id:<20} {field_name:<40} [{field_type}]")
            
            if is_relevant:
                relevant_fields.append({
                    'id': field_id,
                    'name': field_name,
                    'type': 'number' if field_type == 'number' else 'text'
                })
        
        if output:
            # Generate YAML for the discovered fields
            click.echo()
            click.echo("📝 Configuration section for relevant fields:")
            click.echo("custom_fields:")
            for field in relevant_fields:
                click.echo(f"  - id: \"{field['id']}\"")
                click.echo(f"    name: \"{field['name']}\"")
                click.echo(f"    type: \"{field['type']}\"")
                click.echo()
            
            if output != '-':
                # Write to file
                with open(output, 'w') as f:
                    f.write("custom_fields:\n")
                    for field in relevant_fields:
                        f.write(f"  - id: \"{field['id']}\"\n")
                        f.write(f"    name: \"{field['name']}\"\n")
                        f.write(f"    type: \"{field['type']}\"\n")
                        f.write("\n")
                click.echo(f"✓ Configuration written to: {output}")
        
        click.echo()
        click.echo("💡 Tips:")
        click.echo("  • Fields marked with ⭐ are likely useful for search and filtering")
        click.echo("  • Add relevant fields to your config.yaml custom_fields section")
        click.echo("  • Re-sync your data after adding custom fields: python -m jira_search sync --full")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except JiraClientError as e:
        click.echo(f"✗ Jira API error: {e}", err=True)
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
                    issue_key = issue.get('key')
                    
                    # Use the database method that handles existence checking internally
                    was_existing = db.upsert_issue_with_stats(issue)
                    synced_count += 1
                    
                    if was_existing:
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


@cli.command('reset-db')
@click.option('--force', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def reset_database(ctx, force: bool):
    """Drop and recreate the database (WARNING: This will delete all data!)."""
    config_path = ctx.obj['config_path']
    
    try:
        config = load_config(config_path)
        db = Database(config)
        
        if db.exists():
            # Show warning and confirm
            click.echo("⚠️  WARNING: This will permanently delete all synced data!")
            click.echo(f"Database file: {db.db_path}")
            
            if not force:
                if not click.confirm("Are you sure you want to continue?"):
                    click.echo("Operation cancelled.")
                    return
            
            # Get current stats before deletion
            try:
                stats = db.get_statistics()
                total_issues = stats.get('total_issues', 0)
            except Exception:
                total_issues = 0
            
            # Remove the database file
            import os
            if os.path.exists(db.db_path):
                os.remove(db.db_path)
                click.echo(f"✓ Deleted existing database ({total_issues} issues)")
            
        # Recreate the database
        db.initialize()
        click.echo("✓ Created new empty database")
        click.echo()
        click.echo("Next steps:")
        click.echo("1. Run sync to populate with data: python -m jira_search sync")
        click.echo("2. Start the web interface: python -m jira_search serve")
        
    except ConfigError as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Database reset failed: {e}", err=True)
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