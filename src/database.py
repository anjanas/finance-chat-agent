"""SQLite3 database module for tracking agent statistics and experiments."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import contextmanager

from config import logger


class ExperimentTracker:
    """Database tracker for agent statistics and experiments."""
    
    def __init__(self, db_path: str = "experiment_tracker.db"):
        """Initialize the experiment tracker database."""
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Main queries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    context_id TEXT,
                    user_query TEXT NOT NULL,
                    prompt_mode TEXT,
                    main_model TEXT,
                    intent_classifier_model TEXT,
                    judge_model TEXT,
                    is_financial INTEGER,
                    date_check_passed INTEGER,
                    intent_classified TEXT,
                    status TEXT,
                    response TEXT,
                    response_time_ms REAL,
                    iterations INTEGER,
                    judge_approved INTEGER,
                    judge_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            
            # Token usage table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER,
                    model_name TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES queries(id)
                )
            """)
            
            # Tool calls table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER,
                    iteration INTEGER,
                    tool_name TEXT,
                    tool_args TEXT,
                    tool_result TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES queries(id)
                )
            """)
            
            # Guardrail checks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guardrail_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER,
                    check_type TEXT,
                    passed INTEGER,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES queries(id)
                )
            """)
            
            conn.commit()
            logger.info(f"Experiment tracker database initialized: {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper error handling."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def update_query(
        self,
        query_id: int,
        status: Optional[str] = None,
        response: Optional[str] = None,
        response_time_ms: Optional[float] = None,
        iterations: Optional[int] = None,
        judge_approved: Optional[bool] = None,
        judge_reason: Optional[str] = None,
    ):
        """Update an existing query record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if response is not None:
                updates.append("response = ?")
                params.append(response)
            if response_time_ms is not None:
                updates.append("response_time_ms = ?")
                params.append(response_time_ms)
            if iterations is not None:
                updates.append("iterations = ?")
                params.append(iterations)
            if judge_approved is not None:
                updates.append("judge_approved = ?")
                params.append(1 if judge_approved else 0)
            if judge_reason is not None:
                updates.append("judge_reason = ?")
                params.append(judge_reason)
            
            if updates:
                params.append(query_id)
                cursor.execute(f"""
                    UPDATE queries
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, params)
                conn.commit()
    
    def log_query(
        self,
        user_query: str,
        context_id: Optional[str] = None,
        prompt_mode: Optional[str] = None,
        main_model: Optional[str] = None,
        intent_classifier_model: Optional[str] = None,
        judge_model: Optional[str] = None,
        is_financial: Optional[bool] = None,
        date_check_passed: Optional[bool] = None,
        intent_classified: Optional[str] = None,
        status: Optional[str] = None,
        response: Optional[str] = None,
        response_time_ms: Optional[float] = None,
        iterations: Optional[int] = None,
        judge_approved: Optional[bool] = None,
        judge_reason: Optional[str] = None,
    ) -> int:
        """Log a query and return the query ID."""
        timestamp = datetime.utcnow().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO queries (
                    timestamp, context_id, user_query, prompt_mode,
                    main_model, intent_classifier_model, judge_model,
                    is_financial, date_check_passed, intent_classified,
                    status, response, response_time_ms, iterations,
                    judge_approved, judge_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp, context_id, user_query, prompt_mode,
                main_model, intent_classifier_model, judge_model,
                1 if is_financial else 0 if is_financial is not None else None,
                1 if date_check_passed else 0 if date_check_passed is not None else None,
                intent_classified, status, response, response_time_ms,
                iterations, 1 if judge_approved else 0 if judge_approved is not None else None,
                judge_reason
            ))
            query_id = cursor.lastrowid
            conn.commit()
            return query_id
    
    def log_token_usage(
        self,
        query_id: int,
        model_name: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ):
        """Log token usage for a query."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO token_usage (
                    query_id, model_name, prompt_tokens, completion_tokens, total_tokens
                ) VALUES (?, ?, ?, ?, ?)
            """, (query_id, model_name, prompt_tokens, completion_tokens, total_tokens))
            conn.commit()
    
    def log_tool_call(
        self,
        query_id: int,
        iteration: int,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None,
    ):
        """Log a tool call."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tool_calls (
                    query_id, iteration, tool_name, tool_args, tool_result
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                query_id,
                iteration,
                tool_name,
                json.dumps(tool_args) if tool_args else None,
                json.dumps(tool_result) if tool_result else None,
            ))
            conn.commit()
    
    def log_guardrail_check(
        self,
        query_id: int,
        check_type: str,
        passed: bool,
        details: Optional[str] = None,
    ):
        """Log a guardrail check result."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO guardrail_checks (
                    query_id, check_type, passed, details
                ) VALUES (?, ?, ?, ?)
            """, (query_id, check_type, 1 if passed else 0, details))
            conn.commit()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get aggregated statistics from the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # Total queries
            cursor.execute("SELECT COUNT(*) as count FROM queries")
            stats["total_queries"] = cursor.fetchone()["count"]
            
            # Queries by status
            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM queries 
                WHERE status IS NOT NULL
                GROUP BY status
            """)
            stats["queries_by_status"] = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            # Guardrail pass rates
            cursor.execute("""
                SELECT check_type, 
                       SUM(passed) as passed_count,
                       COUNT(*) as total_count
                FROM guardrail_checks
                GROUP BY check_type
            """)
            guardrail_stats = {}
            for row in cursor.fetchall():
                guardrail_stats[row["check_type"]] = {
                    "passed": row["passed_count"],
                    "total": row["total_count"],
                    "pass_rate": row["passed_count"] / row["total_count"] if row["total_count"] > 0 else 0
                }
            stats["guardrail_stats"] = guardrail_stats
            
            # Average response time
            cursor.execute("""
                SELECT AVG(response_time_ms) as avg_time
                FROM queries
                WHERE response_time_ms IS NOT NULL
            """)
            result = cursor.fetchone()
            stats["avg_response_time_ms"] = result["avg_time"] if result["avg_time"] else None
            
            # Total token usage
            cursor.execute("""
                SELECT 
                    SUM(prompt_tokens) as total_prompt_tokens,
                    SUM(completion_tokens) as total_completion_tokens,
                    SUM(total_tokens) as total_tokens
                FROM token_usage
            """)
            token_result = cursor.fetchone()
            stats["token_usage"] = {
                "total_prompt_tokens": token_result["total_prompt_tokens"] or 0,
                "total_completion_tokens": token_result["total_completion_tokens"] or 0,
                "total_tokens": token_result["total_tokens"] or 0,
            }
            
            # Judge approval rate
            cursor.execute("""
                SELECT 
                    SUM(judge_approved) as approved_count,
                    COUNT(*) as total_count
                FROM queries
                WHERE judge_approved IS NOT NULL
            """)
            judge_result = cursor.fetchone()
            if judge_result and judge_result["total_count"] > 0:
                stats["judge_approval_rate"] = judge_result["approved_count"] / judge_result["total_count"]
            else:
                stats["judge_approval_rate"] = None
            
            return stats


# Global instance
_tracker: Optional[ExperimentTracker] = None


def get_tracker() -> ExperimentTracker:
    """Get or create the global experiment tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = ExperimentTracker()
    return _tracker
