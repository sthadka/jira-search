"""SQLite database management for Jira Search."""

import sqlite3
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from jira_search.config import Config

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Database-related errors."""
    pass


class Database:
    """SQLite database manager for Jira issues."""
    
    def __init__(self, config: Config):
        """Initialize database manager.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.db_path = config.database_path
        self.custom_fields = config.custom_fields
    
    def exists(self) -> bool:
        """Check if database file exists."""
        return os.path.exists(self.db_path)
    
    def initialize(self) -> None:
        """Initialize database with schema and indexes."""
        try:
            logger.info(f"Initializing database: {self.db_path}")
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for concurrent reads
                conn.execute("PRAGMA foreign_keys=ON")
                
                # Create main issues table
                self._create_issues_table(conn)
                
                # Create FTS5 virtual table for search
                self._create_fts_table(conn)
                
                # Create metadata table
                self._create_metadata_table(conn)
                
                # Create indexes
                self._create_indexes(conn)
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to initialize database: {e}")
    
    def _create_issues_table(self, conn: sqlite3.Connection) -> None:
        """Create the main issues table with configurable core fields."""
        # Build core field columns dynamically
        core_field_columns = []
        
        # Always include required fields
        required_columns = [
            "key TEXT PRIMARY KEY",
            "summary TEXT NOT NULL"
        ]
        
        # Map core fields to database columns
        field_mappings = {
            'description': 'description TEXT',
            'status': 'status_id TEXT, status_name TEXT',
            'priority': 'priority_id TEXT, priority_name TEXT', 
            'assignee': 'assignee_key TEXT, assignee_name TEXT, assignee_display_name TEXT',
            'reporter': 'reporter_key TEXT, reporter_name TEXT, reporter_display_name TEXT',
            'created': 'created DATETIME',
            'updated': 'updated DATETIME',
            'comment': 'comments TEXT',
            'labels': 'labels TEXT',
            'components': 'components TEXT',
            'fixVersions': 'fix_versions TEXT',
            'affectedVersions': 'affected_versions TEXT'
        }
        
        # Add columns for configured core fields
        for field in self.config.core_fields:
            if field in ['key', 'summary']:
                continue  # Already included as required
            
            if field in field_mappings:
                core_field_columns.append(field_mappings[field])
        
        # Add project and issue type (commonly needed)
        core_field_columns.extend([
            'project_key TEXT',
            'project_name TEXT', 
            'issue_type TEXT'
        ])
        
        # Build custom field columns
        custom_field_columns = []
        for field in self.custom_fields:
            column_name = f"custom_{field['id'].replace('customfield_', '')}"
            if field.get('type') == 'number':
                column_type = 'REAL'
            else:
                column_type = 'TEXT'
            custom_field_columns.append(f"{column_name} {column_type}")
        
        # Combine all columns
        all_columns = required_columns + core_field_columns + custom_field_columns
        all_columns.extend([
            'raw_json TEXT',
            'synced_at DATETIME DEFAULT CURRENT_TIMESTAMP',
            'is_deleted BOOLEAN DEFAULT FALSE',
            'deleted_at DATETIME'
        ])
        
        # Clean up any empty or invalid columns
        all_columns = [col.strip() for col in all_columns if col.strip()]
        
        sql = f"""
        CREATE TABLE IF NOT EXISTS issues (
            {',\n    '.join(all_columns)}
        )
        """
        
        logger.debug(f"Creating table with SQL: {sql}")
        
        conn.execute(sql)
    
    def _create_fts_table(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual table for full-text search using configurable search fields."""
        # Map search fields to database columns
        search_field_mappings = {
            'key': 'key UNINDEXED',  # Include key but don't index it for FTS
            'summary': 'summary',
            'description': 'description', 
            'comment': 'comments',
            'labels': 'labels',
            'components': 'components',
            'assignee': 'assignee_display_name',
            'reporter': 'reporter_display_name'
        }
        
        # Build FTS columns from configured search fields
        fts_columns = []
        for field in self.config.search_fields:
            if field in search_field_mappings:
                fts_columns.append(search_field_mappings[field])
        
        # Always include key (unindexed) and project name for context
        if 'key UNINDEXED' not in fts_columns:
            fts_columns.insert(0, 'key UNINDEXED')
        fts_columns.append('project_name')
        
        # Add custom field columns for FTS (text only)
        for field in self.custom_fields:
            if field.get('type') != 'number':  # Only include text fields in FTS
                column_name = f"custom_{field['id'].replace('customfield_', '')}"
                fts_columns.append(column_name)
        
        sql = f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
            {', '.join(fts_columns)},
            content='issues',
            content_rowid='rowid'
        )
        """
        
        conn.execute(sql)
        
        # Create triggers to keep FTS table in sync
        # Map FTS columns to actual database columns for triggers
        fts_to_db_columns = []
        for fts_col in fts_columns:
            if fts_col == 'key UNINDEXED':
                fts_to_db_columns.append('key')
            elif ' ' in fts_col:  # Remove any extra qualifiers
                fts_to_db_columns.append(fts_col.split()[0])
            else:
                fts_to_db_columns.append(fts_col)
        
        # Add rowid at the beginning for FTS
        trigger_columns = ['rowid'] + fts_to_db_columns
        insert_columns = ', '.join(trigger_columns)
        
        new_values = []
        old_values = []
        for col in trigger_columns:
            new_values.append(f'new.{col}')
            old_values.append(f'old.{col}')
        
        insert_values = ', '.join(new_values)
        delete_values = ', '.join(old_values)
        
        # INSERT trigger
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS issues_fts_insert AFTER INSERT ON issues BEGIN
                INSERT INTO issues_fts({insert_columns})
                VALUES ({insert_values});
            END
        """)
        
        # DELETE trigger
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS issues_fts_delete AFTER DELETE ON issues BEGIN
                INSERT INTO issues_fts(issues_fts, {insert_columns})
                VALUES ('delete', {delete_values});
            END
        """)
        
        # UPDATE trigger
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS issues_fts_update AFTER UPDATE ON issues BEGIN
                INSERT INTO issues_fts(issues_fts, {insert_columns})
                VALUES ('delete', {delete_values});
                INSERT INTO issues_fts({insert_columns})
                VALUES ({insert_values});
            END
        """)
    
    def _create_metadata_table(self, conn: sqlite3.Connection) -> None:
        """Create metadata table for sync tracking."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY,
                last_sync_time DATETIME,
                last_sync_query TEXT,
                last_full_sync DATETIME,
                issues_processed INTEGER DEFAULT 0,
                issues_added INTEGER DEFAULT 0,
                issues_updated INTEGER DEFAULT 0,
                issues_deleted INTEGER DEFAULT 0,
                sync_duration_seconds REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert initial row if not exists
        conn.execute("""
            INSERT OR IGNORE INTO sync_metadata (id, last_sync_time, last_sync_query, last_full_sync)
            VALUES (1, NULL, NULL, NULL)
        """)
    
    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        """Create database indexes for performance."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_issues_updated ON issues(updated)",
            "CREATE INDEX IF NOT EXISTS idx_issues_assignee ON issues(assignee_key)",
            "CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status_name)",
            "CREATE INDEX IF NOT EXISTS idx_issues_priority ON issues(priority_name)",
            "CREATE INDEX IF NOT EXISTS idx_issues_project ON issues(project_key)",
            "CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(created)",
            "CREATE INDEX IF NOT EXISTS idx_issues_synced_at ON issues(synced_at)",
            "CREATE INDEX IF NOT EXISTS idx_issues_is_deleted ON issues(is_deleted)",
            "CREATE INDEX IF NOT EXISTS idx_issues_deleted_at ON issues(deleted_at)"
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
    
    def upsert_issue(self, issue_data: Dict[str, Any]) -> None:
        """Insert or update an issue in the database.
        
        Args:
            issue_data: Issue data from Jira API
        """
        try:
            processed_data = self._process_issue_data(issue_data)
            
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                # Set WAL mode for better concurrency handling
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                # Build dynamic SQL based on configured core fields and custom fields
                columns = ['key', 'summary']  # Always required
                placeholders = ['?', '?']
                values = [processed_data['key'], processed_data['summary']]
                
                # Add configurable core fields
                field_mappings = {
                    'description': 'description',
                    'status': ['status_id', 'status_name'],
                    'priority': ['priority_id', 'priority_name'], 
                    'assignee': ['assignee_key', 'assignee_name', 'assignee_display_name'],
                    'reporter': ['reporter_key', 'reporter_name', 'reporter_display_name'],
                    'created': 'created',
                    'updated': 'updated',
                    'comment': 'comments',
                    'labels': 'labels',
                    'components': 'components',
                    'fixVersions': 'fix_versions',
                    'affectedVersions': 'affected_versions'
                }
                
                for field in self.config.core_fields:
                    if field in ['key', 'summary']:
                        continue  # Already handled
                    
                    if field in field_mappings:
                        mapping = field_mappings[field]
                        if isinstance(mapping, list):
                            # Multiple columns for this field
                            for col in mapping:
                                columns.append(col)
                                placeholders.append('?')
                                values.append(processed_data.get(col))
                        else:
                            # Single column
                            columns.append(mapping)
                            placeholders.append('?')
                            values.append(processed_data.get(mapping))
                
                # Add project and issue type (commonly needed)
                columns.extend(['project_key', 'project_name', 'issue_type'])
                placeholders.extend(['?', '?', '?'])
                values.extend([
                    processed_data.get('project_key'),
                    processed_data.get('project_name'),
                    processed_data.get('issue_type')
                ])
                
                # Add custom fields
                for field in self.custom_fields:
                    column_name = f"custom_{field['id'].replace('customfield_', '')}"
                    columns.append(column_name)
                    placeholders.append('?')
                    values.append(processed_data.get(field['id']))
                
                # Add metadata fields
                columns.extend(['raw_json'])
                placeholders.extend(['?'])
                values.append(json.dumps(issue_data))
                
                sql = f"""
                INSERT OR REPLACE INTO issues (
                    {', '.join(columns)}
                ) VALUES ({', '.join(placeholders)})
                """
                
                conn.execute(sql, values)
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to upsert issue {issue_data.get('key', 'unknown')}: {e}")
    
    def upsert_issue_with_stats(self, issue_data: Dict[str, Any]) -> bool:
        """Insert or update an issue and return whether it was existing.
        
        Args:
            issue_data: Issue data from Jira API
            
        Returns:
            True if issue was updated (existed), False if it was inserted (new)
            
        Raises:
            DatabaseError: If operation fails
        """
        try:
            processed_data = self._process_issue_data(issue_data)
            issue_key = processed_data['key']
            
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                # Set WAL mode for better concurrency handling
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                
                # Check if issue exists in a single transaction
                cursor = conn.execute("SELECT key FROM issues WHERE key = ?", (issue_key,))
                existing = cursor.fetchone()
                
                # Build dynamic SQL based on configured core fields and custom fields
                columns = ['key', 'summary']  # Always required
                placeholders = ['?', '?']
                values = [processed_data['key'], processed_data['summary']]
                
                # Add configurable core fields
                field_mappings = {
                    'description': 'description',
                    'status': ['status_id', 'status_name'],
                    'priority': ['priority_id', 'priority_name'], 
                    'assignee': ['assignee_key', 'assignee_name', 'assignee_display_name'],
                    'reporter': ['reporter_key', 'reporter_name', 'reporter_display_name'],
                    'created': 'created',
                    'updated': 'updated',
                    'comment': 'comments',
                    'labels': 'labels',
                    'components': 'components',
                    'fixVersions': 'fix_versions',
                    'affectedVersions': 'affected_versions'
                }
                
                for field in self.config.core_fields:
                    if field in ['key', 'summary']:
                        continue  # Already handled
                    
                    if field in field_mappings:
                        mapping = field_mappings[field]
                        if isinstance(mapping, list):
                            # Multiple columns for this field
                            for col in mapping:
                                columns.append(col)
                                placeholders.append('?')
                                values.append(processed_data.get(col))
                        else:
                            # Single column
                            columns.append(mapping)
                            placeholders.append('?')
                            values.append(processed_data.get(mapping))
                
                # Add project and issue type (commonly needed)
                columns.extend(['project_key', 'project_name', 'issue_type'])
                placeholders.extend(['?', '?', '?'])
                values.extend([
                    processed_data.get('project_key'),
                    processed_data.get('project_name'),
                    processed_data.get('issue_type')
                ])
                
                # Add custom fields
                for field in self.custom_fields:
                    column_name = f"custom_{field['id'].replace('customfield_', '')}"
                    columns.append(column_name)
                    placeholders.append('?')
                    values.append(processed_data.get(field['id']))
                
                # Add metadata fields
                columns.extend(['raw_json'])
                placeholders.extend(['?'])
                values.append(json.dumps(issue_data))
                
                sql = f"""
                INSERT OR REPLACE INTO issues (
                    {', '.join(columns)}
                ) VALUES ({', '.join(placeholders)})
                """
                
                conn.execute(sql, values)
                return existing is not None
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to upsert issue {issue_data.get('key', 'unknown')}: {e}")
    
    def _process_issue_data(self, issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process raw Jira issue data for database storage.
        
        Args:
            issue_data: Raw issue data from Jira API
            
        Returns:
            Processed data ready for database insertion
        """
        fields = issue_data.get('fields', {})
        
        processed = {
            'key': issue_data.get('key'),
            'summary': fields.get('summary', '')
        }
        
        # Process core fields dynamically based on configuration
        for field in self.config.core_fields:
            if field in ['key', 'summary']:
                continue  # Already handled
                
            if field == 'description':
                processed['description'] = fields.get('description', '')
                
            elif field == 'status':
                status = fields.get('status') or {}
                processed['status_id'] = status.get('id')
                processed['status_name'] = status.get('name')
                
            elif field == 'priority':
                priority = fields.get('priority') or {}
                processed['priority_id'] = priority.get('id')
                processed['priority_name'] = priority.get('name')
                
            elif field == 'assignee':
                assignee = fields.get('assignee') or {}
                processed['assignee_key'] = assignee.get('key') if assignee else None
                processed['assignee_name'] = assignee.get('name') if assignee else None
                processed['assignee_display_name'] = assignee.get('displayName') if assignee else None
                
            elif field == 'reporter':
                reporter = fields.get('reporter') or {}
                processed['reporter_key'] = reporter.get('key') if reporter else None
                processed['reporter_name'] = reporter.get('name') if reporter else None
                processed['reporter_display_name'] = reporter.get('displayName') if reporter else None
                
            elif field == 'created':
                processed['created'] = fields.get('created')
                
            elif field == 'updated':
                processed['updated'] = fields.get('updated')
                
            elif field == 'comment':
                # Combine all comments into a single searchable text field
                comments_text = ""
                comments = fields.get('comment', {}).get('comments', [])
                if comments:
                    comment_texts = []
                    for comment in comments:
                        author = comment.get('author', {}).get('displayName', 'Unknown')
                        body = comment.get('body', '')
                        comment_texts.append(f"{author}: {body}")
                    comments_text = "\n".join(comment_texts)
                processed['comments'] = comments_text
                
            elif field == 'labels':
                # Process labels array into searchable text
                labels = fields.get('labels', [])
                processed['labels'] = ", ".join(labels) if labels else ""
                
            elif field == 'components':
                # Process components array
                components = fields.get('components', [])
                if components:
                    component_names = [comp.get('name', '') for comp in components if comp.get('name')]
                    processed['components'] = ", ".join(component_names)
                else:
                    processed['components'] = ""
                    
            elif field == 'fixVersions':
                # Process fix versions array
                fix_versions = fields.get('fixVersions', [])
                if fix_versions:
                    version_names = [ver.get('name', '') for ver in fix_versions if ver.get('name')]
                    processed['fix_versions'] = ", ".join(version_names)
                else:
                    processed['fix_versions'] = ""
                    
            elif field == 'affectedVersions':
                # Process affected versions array
                affected_versions = fields.get('versions', [])
                if affected_versions:
                    version_names = [ver.get('name', '') for ver in affected_versions if ver.get('name')]
                    processed['affected_versions'] = ", ".join(version_names)
                else:
                    processed['affected_versions'] = ""
        
        # Always extract project and issue type info (commonly needed)
        project = fields.get('project') or {}
        processed['project_key'] = project.get('key')
        processed['project_name'] = project.get('name')
        
        issue_type_obj = fields.get('issuetype') or {}
        processed['issue_type'] = issue_type_obj.get('name')
        
        # Add custom fields
        for field in self.custom_fields:
            field_id = field['id']
            field_value = fields.get(field_id)
            
            # Process different field types
            if field_value is not None:
                if field.get('type') == 'number':
                    try:
                        processed[field_id] = float(field_value)
                    except (ValueError, TypeError):
                        processed[field_id] = None
                else:
                    # Handle various field types (text, select, etc.)
                    if isinstance(field_value, dict):
                        processed[field_id] = field_value.get('value') or field_value.get('name') or str(field_value)
                    elif isinstance(field_value, list) and field_value:
                        # Multi-select fields
                        values = []
                        for item in field_value:
                            if isinstance(item, dict):
                                values.append(item.get('value') or item.get('name') or str(item))
                            else:
                                values.append(str(item))
                        processed[field_id] = ", ".join(values)
                    else:
                        processed[field_id] = str(field_value) if field_value else None
            else:
                processed[field_id] = None
        
        return processed
    
    def clear_issues(self) -> None:
        """Clear all issues from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM issues")
                # FTS table will be cleared automatically by triggers
                logger.info("All issues cleared from database")
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to clear issues: {e}")
    
    def update_sync_metadata(self, sync_query: str, is_full_sync: bool = False, 
                           sync_stats: Optional[Dict[str, int]] = None, 
                           duration_seconds: float = 0) -> None:
        """Update sync metadata after successful sync.
        
        Args:
            sync_query: JQL query used for sync
            is_full_sync: Whether this was a full sync
            sync_stats: Dictionary with sync statistics
            duration_seconds: How long the sync took
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now().isoformat()
                stats = sync_stats or {}
                
                if is_full_sync:
                    conn.execute("""
                        UPDATE sync_metadata 
                        SET last_sync_time = ?, last_sync_query = ?, last_full_sync = ?,
                            issues_processed = ?, issues_added = ?, issues_updated = ?, 
                            issues_deleted = ?, sync_duration_seconds = ?, updated_at = ?
                        WHERE id = 1
                    """, (now, sync_query, now, 
                          stats.get('processed', 0), stats.get('added', 0), 
                          stats.get('updated', 0), stats.get('deleted', 0),
                          duration_seconds, now))
                else:
                    conn.execute("""
                        UPDATE sync_metadata 
                        SET last_sync_time = ?, last_sync_query = ?,
                            issues_processed = ?, issues_added = ?, issues_updated = ?, 
                            issues_deleted = ?, sync_duration_seconds = ?, updated_at = ?
                        WHERE id = 1
                    """, (now, sync_query, 
                          stats.get('processed', 0), stats.get('added', 0), 
                          stats.get('updated', 0), stats.get('deleted', 0),
                          duration_seconds, now))
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to update sync metadata: {e}")
    
    def mark_issue_deleted(self, issue_key: str) -> None:
        """Mark an issue as deleted instead of removing it.
        
        Args:
            issue_key: Jira issue key
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE issues 
                    SET is_deleted = TRUE, deleted_at = ?
                    WHERE key = ?
                """, (datetime.now().isoformat(), issue_key))
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to mark issue as deleted: {e}")
    
    def cleanup_deleted_issues(self, days_old: int = 30) -> int:
        """Remove issues that have been marked as deleted for a specified time.
        
        Args:
            days_old: Number of days since deletion to keep issues
            
        Returns:
            Number of issues permanently removed
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
                
                # Count issues to be deleted
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM issues 
                    WHERE is_deleted = TRUE AND deleted_at < ?
                """, (cutoff_date,))
                count = cursor.fetchone()[0]
                
                # Delete old deleted issues
                conn.execute("""
                    DELETE FROM issues 
                    WHERE is_deleted = TRUE AND deleted_at < ?
                """, (cutoff_date,))
                
                return count
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to cleanup deleted issues: {e}")
    
    def get_deleted_issues(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get list of recently deleted issues.
        
        Args:
            limit: Maximum number of deleted issues to return
            
        Returns:
            List of deleted issue information
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT key, summary, deleted_at, project_key
                    FROM issues 
                    WHERE is_deleted = TRUE 
                    ORDER BY deleted_at DESC 
                    LIMIT ?
                """, (limit,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get deleted issues: {e}")
    
    def get_last_sync_time(self) -> Optional[str]:
        """Get the last sync timestamp for incremental sync.
        
        Returns:
            ISO formatted timestamp string or None if never synced
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT last_sync_time FROM sync_metadata WHERE id = 1
                """)
                result = cursor.fetchone()
                return result[0] if result and result[0] else None
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get last sync time: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics and sync information.
        
        Returns:
            Dictionary with database statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get total issues count
                cursor = conn.execute("SELECT COUNT(*) FROM issues")
                total_issues = cursor.fetchone()[0]
                
                # Get sync metadata
                cursor = conn.execute("""
                    SELECT last_sync_time, last_sync_query, last_full_sync,
                           issues_processed, issues_added, issues_updated, 
                           issues_deleted, sync_duration_seconds
                    FROM sync_metadata WHERE id = 1
                """)
                sync_data = cursor.fetchone()
                if sync_data:
                    last_sync_time, last_sync_query, last_full_sync, issues_processed, \
                    issues_added, issues_updated, issues_deleted, sync_duration_seconds = sync_data
                else:
                    last_sync_time = last_sync_query = last_full_sync = None
                    issues_processed = issues_added = issues_updated = issues_deleted = sync_duration_seconds = 0
                
                # Get oldest and newest issues
                cursor = conn.execute("SELECT key FROM issues ORDER BY created ASC LIMIT 1")
                oldest_issue = cursor.fetchone()
                oldest_issue = oldest_issue[0] if oldest_issue else None
                
                cursor = conn.execute("SELECT key FROM issues ORDER BY created DESC LIMIT 1")
                newest_issue = cursor.fetchone()
                newest_issue = newest_issue[0] if newest_issue else None
                
                # Get database file size
                db_size_bytes = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                db_size_mb = db_size_bytes / (1024 * 1024)
                
                return {
                    'total_issues': total_issues,
                    'last_sync_time': last_sync_time,
                    'last_sync_query': last_sync_query,
                    'last_full_sync': last_full_sync,
                    'issues_processed': issues_processed,
                    'issues_added': issues_added,
                    'issues_updated': issues_updated,
                    'issues_deleted': issues_deleted,
                    'sync_duration_seconds': sync_duration_seconds,
                    'oldest_issue': oldest_issue,
                    'newest_issue': newest_issue,
                    'database_size_mb': db_size_mb
                }
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get statistics: {e}")
    
    def search_issues(self, query: str, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Search issues using FTS5 with fallback for exact matches.
        
        Args:
            query: Search query
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            Tuple of (results list, total count)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Check if query looks like an exact issue key for direct lookup
                import re
                if re.match(r'^[A-Z]+-\d+$', query.strip()):
                    # Direct key lookup for exact issue key matches
                    cursor = conn.execute("""
                        SELECT *, 1 as rank FROM issues 
                        WHERE key = ? AND (is_deleted IS NULL OR is_deleted = FALSE)
                        LIMIT ? OFFSET ?
                    """, (query.strip(), limit, offset))
                    
                    results = [dict(row) for row in cursor.fetchall()]
                    
                    if results:
                        # Found exact match
                        cursor = conn.execute("""
                            SELECT COUNT(*) FROM issues 
                            WHERE key = ? AND (is_deleted IS NULL OR is_deleted = FALSE)
                        """, (query.strip(),))
                        total = cursor.fetchone()[0]
                        return results, total
                
                # Fall back to FTS5 search for other queries
                fts_query = self._sanitize_fts_query(query)
                
                cursor = conn.execute("""
                    SELECT i.*, rank 
                    FROM issues_fts fts
                    JOIN issues i ON i.rowid = fts.rowid
                    WHERE issues_fts MATCH ? AND (i.is_deleted IS NULL OR i.is_deleted = FALSE)
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                """, (fts_query, limit, offset))
                
                results = [dict(row) for row in cursor.fetchall()]
                
                # Get total count
                cursor = conn.execute("""
                    SELECT COUNT(*)
                    FROM issues_fts fts
                    JOIN issues i ON i.rowid = fts.rowid
                    WHERE issues_fts MATCH ? AND (i.is_deleted IS NULL OR i.is_deleted = FALSE)
                """, (fts_query,))
                
                total = cursor.fetchone()[0]
                
                return results, total
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Search failed: {e}")
    
    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query for FTS5 to handle special characters and operators.
        
        Args:
            query: Raw search query
            
        Returns:
            Sanitized FTS5 query
        """
        if not query or not query.strip():
            return '""'  # Empty query
            
        query = query.strip()
        
        # Check if it looks like an issue key (PROJECT-NUMBER format)
        import re
        if re.match(r'^[A-Z]+-\d+$', query):
            # For issue keys, quote the entire string to prevent FTS5 from parsing the hyphen
            return f'"{query}"'
        
        # Check for other special FTS5 characters that need escaping
        special_chars = ['-', ':', '(', ')', '[', ']', '{', '}', '"']
        
        # If query contains special chars but isn't already quoted, quote it
        if any(char in query for char in special_chars) and not (query.startswith('"') and query.endswith('"')):
            # Escape any existing quotes in the query
            escaped_query = query.replace('"', '""')
            return f'"{escaped_query}"'
        
        # Return as-is for simple queries
        return query