"""SQLite database management for Jira Search Mirror."""

import sqlite3
import json
import logging
import os
from datetime import datetime
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
        """Create the main issues table."""
        # Build custom field columns
        custom_field_columns = []
        for field in self.custom_fields:
            column_name = f"custom_{field['id'].replace('customfield_', '')}"
            if field.get('type') == 'number':
                column_type = 'REAL'
            else:
                column_type = 'TEXT'
            custom_field_columns.append(f"{column_name} {column_type}")
        
        custom_fields_sql = ""
        if custom_field_columns:
            custom_fields_sql = ",\n    " + ",\n    ".join(custom_field_columns)
        
        sql = f"""
        CREATE TABLE IF NOT EXISTS issues (
            key TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            description TEXT,
            status_id TEXT,
            status_name TEXT,
            priority_id TEXT,
            priority_name TEXT,
            assignee_key TEXT,
            assignee_name TEXT,
            assignee_display_name TEXT,
            reporter_key TEXT,
            reporter_name TEXT,
            reporter_display_name TEXT,
            created DATETIME,
            updated DATETIME,
            comments TEXT,
            project_key TEXT,
            project_name TEXT,
            issue_type TEXT{custom_fields_sql},
            raw_json TEXT,
            synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        
        conn.execute(sql)
    
    def _create_fts_table(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual table for full-text search."""
        # Build custom field columns for FTS
        custom_field_columns = []
        for field in self.custom_fields:
            if field.get('type') != 'number':  # Only include text fields in FTS
                column_name = f"custom_{field['id'].replace('customfield_', '')}"
                custom_field_columns.append(column_name)
        
        custom_fields_fts = ""
        if custom_field_columns:
            custom_fields_fts = ", " + ", ".join(custom_field_columns)
        
        sql = f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
            key UNINDEXED,
            summary,
            description,
            comments,
            assignee_display_name,
            reporter_display_name,
            project_name{custom_fields_fts},
            content='issues',
            content_rowid='rowid'
        )
        """
        
        conn.execute(sql)
        
        # Create triggers to keep FTS table in sync with custom fields
        # Build column lists for triggers
        base_columns = ['rowid', 'key', 'summary', 'description', 'comments', 
                       'assignee_display_name', 'reporter_display_name', 'project_name']
        base_columns.extend(custom_field_columns)
        
        insert_columns = ', '.join(base_columns)
        
        new_values = []
        old_values = []
        for col in base_columns:
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert initial row if not exists
        conn.execute("""
            INSERT OR IGNORE INTO sync_metadata (id, last_sync_time, last_sync_query)
            VALUES (1, NULL, NULL)
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
            "CREATE INDEX IF NOT EXISTS idx_issues_synced_at ON issues(synced_at)"
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
            
            with sqlite3.connect(self.db_path) as conn:
                # Build dynamic SQL for custom fields
                custom_field_columns = []
                custom_field_placeholders = []
                custom_field_values = []
                
                for field in self.custom_fields:
                    column_name = f"custom_{field['id'].replace('customfield_', '')}"
                    custom_field_columns.append(column_name)
                    custom_field_placeholders.append("?")
                    custom_field_values.append(processed_data.get(field['id']))
                
                custom_fields_sql = ""
                if custom_field_columns:
                    custom_fields_sql = ", " + ", ".join(custom_field_columns)
                    custom_placeholders_sql = ", " + ", ".join(custom_field_placeholders)
                else:
                    custom_placeholders_sql = ""
                
                sql = f"""
                INSERT OR REPLACE INTO issues (
                    key, summary, description, status_id, status_name, priority_id, priority_name,
                    assignee_key, assignee_name, assignee_display_name,
                    reporter_key, reporter_name, reporter_display_name,
                    created, updated, comments, project_key, project_name, issue_type, raw_json{custom_fields_sql}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{custom_placeholders_sql})
                """
                
                values = [
                    processed_data['key'],
                    processed_data['summary'],
                    processed_data['description'],
                    processed_data['status_id'],
                    processed_data['status_name'],
                    processed_data['priority_id'],
                    processed_data['priority_name'],
                    processed_data['assignee_key'],
                    processed_data['assignee_name'],
                    processed_data['assignee_display_name'],
                    processed_data['reporter_key'],
                    processed_data['reporter_name'],
                    processed_data['reporter_display_name'],
                    processed_data['created'],
                    processed_data['updated'],
                    processed_data['comments'],
                    processed_data['project_key'],
                    processed_data['project_name'],
                    processed_data['issue_type'],
                    json.dumps(issue_data)
                ] + custom_field_values
                
                conn.execute(sql, values)
                
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
        
        # Extract assignee information
        assignee = fields.get('assignee') or {}
        assignee_key = assignee.get('key') if assignee else None
        assignee_name = assignee.get('name') if assignee else None
        assignee_display_name = assignee.get('displayName') if assignee else None
        
        # Extract reporter information
        reporter = fields.get('reporter') or {}
        reporter_key = reporter.get('key') if reporter else None
        reporter_name = reporter.get('name') if reporter else None
        reporter_display_name = reporter.get('displayName') if reporter else None
        
        # Extract status information
        status = fields.get('status') or {}
        status_id = status.get('id')
        status_name = status.get('name')
        
        # Extract priority information
        priority = fields.get('priority') or {}
        priority_id = priority.get('id')
        priority_name = priority.get('name')
        
        # Extract project information
        project = fields.get('project') or {}
        project_key = project.get('key')
        project_name = project.get('name')
        
        # Extract issue type
        issue_type_obj = fields.get('issuetype') or {}
        issue_type = issue_type_obj.get('name')
        
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
        
        processed = {
            'key': issue_data.get('key'),
            'summary': fields.get('summary', ''),
            'description': fields.get('description', ''),
            'status_id': status_id,
            'status_name': status_name,
            'priority_id': priority_id,
            'priority_name': priority_name,
            'assignee_key': assignee_key,
            'assignee_name': assignee_name,
            'assignee_display_name': assignee_display_name,
            'reporter_key': reporter_key,
            'reporter_name': reporter_name,
            'reporter_display_name': reporter_display_name,
            'created': fields.get('created'),
            'updated': fields.get('updated'),
            'comments': comments_text,
            'project_key': project_key,
            'project_name': project_name,
            'issue_type': issue_type
        }
        
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
    
    def update_sync_metadata(self, sync_query: str) -> None:
        """Update sync metadata after successful sync.
        
        Args:
            sync_query: JQL query used for sync
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE sync_metadata 
                    SET last_sync_time = ?, last_sync_query = ?, updated_at = ?
                    WHERE id = 1
                """, (datetime.now().isoformat(), sync_query, datetime.now().isoformat()))
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to update sync metadata: {e}")
    
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
                    SELECT last_sync_time, last_sync_query 
                    FROM sync_metadata WHERE id = 1
                """)
                sync_data = cursor.fetchone()
                last_sync_time = sync_data[0] if sync_data else None
                last_sync_query = sync_data[1] if sync_data else None
                
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
                    'oldest_issue': oldest_issue,
                    'newest_issue': newest_issue,
                    'database_size_mb': db_size_mb
                }
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get statistics: {e}")
    
    def search_issues(self, query: str, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Search issues using FTS5.
        
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
                
                # Search using FTS5
                cursor = conn.execute("""
                    SELECT i.*, rank 
                    FROM issues_fts fts
                    JOIN issues i ON i.rowid = fts.rowid
                    WHERE issues_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                """, (query, limit, offset))
                
                results = [dict(row) for row in cursor.fetchall()]
                
                # Get total count
                cursor = conn.execute("""
                    SELECT COUNT(*)
                    FROM issues_fts
                    WHERE issues_fts MATCH ?
                """, (query,))
                
                total = cursor.fetchone()[0]
                
                return results, total
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Search failed: {e}")