"""Advanced search functionality for JQL and Regex modes."""

import re
import sqlite3
import time
import logging
from typing import Dict, List, Tuple, Any, Optional
from jira_search.database import Database

logger = logging.getLogger(__name__)


class SearchError(Exception):
    """Search-related errors."""

    pass


class JQLError(SearchError):
    """JQL parsing or execution errors."""

    pass


class RegexError(SearchError):
    """Regex search errors."""

    pass


# Map JQL field names to database columns
JQL_FIELD_MAPPING = {
    "project": "project_key",
    "assignee": "assignee_display_name",
    "status": "status_name",
    "priority": "priority_name",
    "created": "created",
    "updated": "updated",
    "summary": "summary",
    "description": "description",
    "reporter": "reporter_display_name",
    "type": "issue_type",
    "issuetype": "issue_type",
    "key": "key",
    "labels": "labels",
    "components": "components",
    # Custom fields
    "team": "custom_12313240",
    "work_type": "custom_12320040",
    "product_manager": "custom_12316752",
    "px_impact_score": "custom_12322244",
}


class AdvancedSearch:
    """Advanced search engine supporting JQL and Regex modes."""

    def __init__(self, database: Database, timeout_seconds: int = 5):
        """Initialize advanced search engine.

        Args:
            database: Database instance
            timeout_seconds: Timeout for regex searches
        """
        self.db = database
        self.timeout_seconds = timeout_seconds

    def search(
        self, query: str, mode: str, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Perform search based on mode.

        Args:
            query: Search query
            mode: Search mode ('natural', 'jql', 'regex')
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (results, total_count)

        Raises:
            SearchError: If search fails
        """
        start_time = time.time()

        try:
            if mode == "natural":
                return self.db.search_issues(query, limit=limit, offset=offset)
            elif mode == "jql":
                return self._search_jql(query, limit=limit, offset=offset)
            elif mode == "regex":
                return self._search_regex(query, limit=limit, offset=offset)
            else:
                raise SearchError(f"Unsupported search mode: {mode}")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"Search failed (mode={mode}, query={query}, elapsed={elapsed:.3f}s): {e}"
            )
            raise

    def _search_jql(
        self, jql_query: str, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search using JQL query.

        Args:
            jql_query: JQL query string
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (results, total_count)

        Raises:
            JQLError: If JQL parsing or execution fails
        """
        try:
            # Parse JQL and convert to SQL
            sql_where, params = self._parse_jql(jql_query)

            # Execute search query
            with sqlite3.connect(self.db.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Main search query
                sql = f"""
                    SELECT * FROM issues
                    WHERE {sql_where}
                    ORDER BY updated DESC
                    LIMIT ? OFFSET ?
                """
                params.extend([limit, offset])

                cursor = conn.execute(sql, params)
                results = [dict(row) for row in cursor.fetchall()]

                # Count total results
                count_sql = f"SELECT COUNT(*) FROM issues WHERE {sql_where}"
                cursor = conn.execute(
                    count_sql, params[:-2]
                )  # Remove limit/offset params
                total = cursor.fetchone()[0]

                return results, total

        except sqlite3.Error as e:
            raise JQLError(f"Database error executing JQL: {e}")
        except Exception as e:
            raise JQLError(f"JQL execution failed: {e}")

    def _parse_jql(self, jql_query: str) -> Tuple[str, List[Any]]:
        """Parse JQL query and convert to SQL WHERE clause.

        Args:
            jql_query: JQL query string

        Returns:
            Tuple of (sql_where_clause, parameters)

        Raises:
            JQLError: If JQL parsing fails
        """
        # Simple JQL parser - handles basic syntax
        # TODO: This is a basic implementation, can be enhanced for more complex JQL

        try:
            # Normalize the query
            query = jql_query.strip()
            if not query:
                raise JQLError("Empty JQL query")

            # Handle simple cases first
            conditions = []
            params = []

            # Split by AND/OR (case-insensitive)
            # For now, we'll handle AND operations, OR can be added later
            and_parts = re.split(r"\s+AND\s+", query, flags=re.IGNORECASE)

            for part in and_parts:
                part = part.strip()
                condition, part_params = self._parse_jql_condition(part)
                conditions.append(condition)
                params.extend(part_params)

            if not conditions:
                raise JQLError("No valid conditions found in JQL")

            sql_where = " AND ".join(conditions)
            return sql_where, params

        except Exception as e:
            raise JQLError(f"Failed to parse JQL '{jql_query}': {e}")

    def _parse_jql_condition(self, condition: str) -> Tuple[str, List[Any]]:
        """Parse a single JQL condition.

        Args:
            condition: Single JQL condition (e.g., "project = ROX")

        Returns:
            Tuple of (sql_condition, parameters)

        Raises:
            JQLError: If condition parsing fails
        """
        condition = condition.strip()

        # Handle different operators
        operators = [
            ("!=", "!="),
            ("=", "="),
            ("IN", "IN"),
            (">", ">"),
            (">=", ">="),
            ("<", "<"),
            ("<=", "<="),
            ("~", "LIKE"),  # JQL contains operator
        ]

        for jql_op, sql_op in operators:
            # Check for operator in condition (case-insensitive for most, but preserve != exactly)
            if jql_op == "!=":
                if " != " in condition:
                    return self._parse_operator_condition(condition, jql_op, sql_op)
            elif f" {jql_op.upper()} " in condition.upper():
                return self._parse_operator_condition(condition, jql_op, sql_op)

        raise JQLError(f"Unsupported JQL condition: {condition}")

    def _parse_operator_condition(
        self, condition: str, jql_op: str, sql_op: str
    ) -> Tuple[str, List[Any]]:
        """Parse a condition with a specific operator.

        Args:
            condition: JQL condition
            jql_op: JQL operator (e.g., '=', '!=', 'IN')
            sql_op: SQL operator

        Returns:
            Tuple of (sql_condition, parameters)
        """
        # Split on the operator (case-insensitive)
        parts = re.split(f"\\s+{re.escape(jql_op)}\\s+", condition, flags=re.IGNORECASE)

        if len(parts) != 2:
            raise JQLError(f"Invalid condition format: {condition}")

        field_name = parts[0].strip()
        value_part = parts[1].strip()

        # Map JQL field to database column
        db_column = JQL_FIELD_MAPPING.get(field_name.lower())
        if not db_column:
            raise JQLError(f"Unsupported JQL field: {field_name}")

        # Handle different value types
        if sql_op == "IN":
            # Handle IN operator: field IN (value1, value2, ...)
            if not (value_part.startswith("(") and value_part.endswith(")")):
                raise JQLError(f"IN operator requires parentheses: {value_part}")

            # Extract values from parentheses
            values_str = value_part[1:-1].strip()
            values = [v.strip().strip("\"'") for v in values_str.split(",")]

            # Special handling for labels and components fields
            if db_column in ["labels", "components"]:
                # For labels/components with IN, check if any values exist
                # in the comma-separated list
                conditions = []
                all_params = []
                for value in values:
                    # Each value can be: exact match, first item, middle item, or last item
                    condition_parts = (
                        f"({db_column} = ? OR {db_column} LIKE ? OR "
                        f"{db_column} LIKE ? OR {db_column} LIKE ?)"
                    )
                    conditions.append(condition_parts)
                    all_params.extend(
                        [value, f"{value},%", f"%, {value}", f"%, {value},%"]
                    )

                sql_condition = f"({' OR '.join(conditions)})"
                return sql_condition, all_params
            else:
                placeholders = ",".join(["?"] * len(values))
                sql_condition = f"{db_column} IN ({placeholders})"
                return sql_condition, values

        elif sql_op == "LIKE":
            # Handle contains operator (~)
            value = value_part.strip("\"'")
            sql_condition = f"{db_column} LIKE ?"
            return sql_condition, [f"%{value}%"]

        else:
            # Handle simple operators (=, !=, >, <, etc.)
            value = value_part.strip("\"'")

            # Handle special JQL values
            if value.lower() == "null":
                if sql_op == "=":
                    return f"{db_column} IS NULL", []
                elif sql_op == "!=":
                    return f"{db_column} IS NOT NULL", []

            # Handle currentUser() function
            if value.lower() == "currentuser()":
                # For now, we don't have current user context, so this will match nothing
                # TODO: Implement user context in future versions
                value = "__CURRENT_USER_PLACEHOLDER__"

            # Special handling for labels and components fields
            # These are stored as comma-separated strings, so we need pattern matching
            if db_column in ["labels", "components"]:
                if sql_op == "=":
                    # For labels/components, = means "contains this label"
                    # Use LIKE with word boundary patterns to avoid partial matches
                    sql_condition = (
                        f"({db_column} = ? OR {db_column} LIKE ? OR "
                        f"{db_column} LIKE ? OR {db_column} LIKE ?)"
                    )
                    return sql_condition, [
                        value,
                        f"{value},%",
                        f"%, {value}",
                        f"%, {value},%",
                    ]
                elif sql_op == "!=":
                    # For labels/components, != means "does not contain this label"
                    sql_condition = (
                        f"({db_column} IS NULL OR ({db_column} != ? AND "
                        f"{db_column} NOT LIKE ? AND {db_column} NOT LIKE ? AND "
                        f"{db_column} NOT LIKE ?))"
                    )
                    return sql_condition, [
                        value,
                        f"{value},%",
                        f"%, {value}",
                        f"%, {value},%",
                    ]
                else:
                    # For other operators on labels/components, use direct comparison
                    sql_condition = f"{db_column} {sql_op} ?"
                    return sql_condition, [value]
            else:
                sql_condition = f"{db_column} {sql_op} ?"
                return sql_condition, [value]

    def _search_regex(
        self, regex_pattern: str, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search using regex pattern with timeout protection.

        Args:
            regex_pattern: Regular expression pattern
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (results, total_count)

        Raises:
            RegexError: If regex search fails or times out
        """
        start_time = time.time()

        try:
            # Validate regex pattern
            try:
                compiled_regex = re.compile(regex_pattern, re.IGNORECASE)
            except re.error as e:
                raise RegexError(f"Invalid regex pattern: {e}")

            # Use SQLite REGEXP operator with timeout protection
            with sqlite3.connect(self.db.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Define custom REGEXP function with timeout check
                def regexp_with_timeout(pattern, text):
                    if time.time() - start_time > self.timeout_seconds:
                        raise RegexError(
                            f"Regex search timed out after {self.timeout_seconds} seconds"
                        )

                    if text is None:
                        return False

                    try:
                        return bool(compiled_regex.search(str(text)))
                    except Exception:
                        return False

                # Register the custom function
                conn.create_function("REGEXP", 2, regexp_with_timeout)

                # Search in multiple text fields
                sql = """
                    SELECT * FROM issues
                    WHERE summary REGEXP ?
                       OR description REGEXP ?
                       OR comments REGEXP ?
                       OR assignee_display_name REGEXP ?
                       OR reporter_display_name REGEXP ?
                       OR custom_12316752 REGEXP ?
                       OR custom_12320040 REGEXP ?
                       OR custom_12313240 REGEXP ?
                    ORDER BY updated DESC
                    LIMIT ? OFFSET ?
                """

                params = [regex_pattern] * 8 + [limit, offset]
                cursor = conn.execute(sql, params)
                results = [dict(row) for row in cursor.fetchall()]

                # Check timeout before counting
                if time.time() - start_time > self.timeout_seconds:
                    raise RegexError(
                        f"Regex search timed out after {self.timeout_seconds} seconds"
                    )

                # Count total results
                count_sql = """
                    SELECT COUNT(*) FROM issues
                    WHERE summary REGEXP ?
                       OR description REGEXP ?
                       OR comments REGEXP ?
                       OR assignee_display_name REGEXP ?
                       OR reporter_display_name REGEXP ?
                       OR custom_12316752 REGEXP ?
                       OR custom_12320040 REGEXP ?
                       OR custom_12313240 REGEXP ?
                """

                count_params = [regex_pattern] * 8
                cursor = conn.execute(count_sql, count_params)
                total = cursor.fetchone()[0]

                return results, total

        except RegexError:
            raise
        except sqlite3.Error as e:
            raise RegexError(f"Database error executing regex: {e}")
        except Exception as e:
            raise RegexError(f"Regex search failed: {e}")

    def validate_jql(self, jql_query: str) -> Tuple[bool, Optional[str]]:
        """Validate JQL query syntax.

        Args:
            jql_query: JQL query to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            self._parse_jql(jql_query)
            return True, None
        except JQLError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Validation error: {e}"

    def validate_regex(self, regex_pattern: str) -> Tuple[bool, Optional[str]]:
        """Validate regex pattern.

        Args:
            regex_pattern: Regex pattern to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            re.compile(regex_pattern)
            return True, None
        except re.error as e:
            return False, f"Invalid regex: {e}"
        except Exception as e:
            return False, f"Validation error: {e}"
