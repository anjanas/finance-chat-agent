import os
import sys
import json
from dataclasses import dataclass

from dotenv import load_dotenv, find_dotenv
from loguru import logger as _logger

# Load .env once when this module is imported
load_dotenv(find_dotenv(), override=True)


@dataclass(frozen=True)
class Settings:
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    NEBIUS_API_KEY: str = os.getenv("NEBIUS_API_KEY")
    MODEL_PROVIDER: str = os.getenv("MODEL_PROVIDER", "nebius")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "moonshotai/Kimi-K2-Instruct")
    
    # Intent classification model (for guardrails and intent classification)
    INTENT_CLASSIFIER_MODEL: str = os.getenv("INTENT_CLASSIFIER_MODEL", "openai/gpt-4o-mini")
    
    # Judge model for answer verification (optional, uses different model to verify answers)
    JUDGE_MODEL_ENABLED: bool = os.getenv("JUDGE_MODEL_ENABLED", "false").lower() in ('true', '1', 't')
    JUDGE_MODEL_NAME: str = os.getenv("JUDGE_MODEL_NAME", "openai/gpt-4o-mini")

    # Tools
    MCP_ENABLED: bool = os.getenv("MCP_ENABLED", "false").lower() in ('true', '1', 't')
    MCP_SERVER: str = os.getenv("MCP_SERVER", "http://127.0.0.1:9020")

    # Finish condition
    MAX_ITERATIONS = 20
    
    # Prompt mode: "detailed", "json", or "auto" (auto uses intent classifier)
    PROMPT_MODE: str = os.getenv("PROMPT_MODE", "json").lower()
    
    # Model training date cutoff (YYYY-MM-DD format)
    # Questions about dates beyond this will be rejected
    MODEL_TRAINING_CUTOFF: str = os.getenv("MODEL_TRAINING_CUTOFF", "2024-04-01")


# Create settings
settings = Settings()

print(f"PROMPT_MODE: {settings.PROMPT_MODE}")

if not settings.NEBIUS_API_KEY or not settings.NEBIUS_API_KEY.strip():
    print(
        "Error: NEBIUS_API_KEY is not set. The finance agent requires a Nebius API key to call the LLM.\n"
        "  - Set it in your environment: export NEBIUS_API_KEY=your_key\n"
        "  - Or add it to a .env file in the project root: NEBIUS_API_KEY=your_key\n"
        "  - Get an API key from https://nebius.com (or your Nebius provider).",
        file=sys.stderr,
    )
    sys.exit(1)


def configure_logger():
    """
    Configure logger to be used
    """
    import os
    from pathlib import Path
    
    # idempotent config: remove existing handlers and add handlers
    _logger.remove()
    
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Log file path
    log_file = log_dir / "finance-purple-agent.log"
    failure_log_file = log_dir / "agent-failures.log"
    success_log_file = log_dir / "agent-successes.log"

    # Add file handler - logs all levels
    _logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
        level=settings.LOG_LEVEL,
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention="7 days",  # Keep logs for 7 days
        compression="zip",  # Compress old log files
        enqueue=True,  # Thread-safe logging
    )

    # Add failure log file - only records with agent_failure=True in extra
    _logger.add(
        str(failure_log_file),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
        level="WARNING",
        filter=lambda record: record["extra"].get("agent_failure") is True,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )

    # Add success log file - only records with agent_success=True in extra
    _logger.add(
        str(success_log_file),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
        level="INFO",
        filter=lambda record: record["extra"].get("agent_success") is True,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )

    # Add console handler - logs to stdout
    _logger.add(
        lambda msg: print(msg, end=""),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
        level=settings.LOG_LEVEL,
    )


def log_agent_failure(
    reason: str,
    *,
    user_message: str | None = None,
    context_id: str | None = None,
    task_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Log an agent failure to the main log and to logs/agent-failures.log."""
    parts = [f"Agent failed to satisfy request: {reason}"]
    if user_message is not None:
        parts.append(f"user_message={user_message!r}")
    if context_id is not None:
        parts.append(f"context_id={context_id}")
    if task_id is not None:
        parts.append(f"task_id={task_id}")
    if detail is not None:
        parts.append(f"detail={detail}")
    _logger.bind(agent_failure=True).warning(" | ".join(parts))


def log_agent_success(
    *,
    user_message: str | None = None,
    context_id: str | None = None,
    task_id: str | None = None,
    response_preview: str | None = None,
) -> None:
    """Log a successful task to the main log and to logs/agent-successes.log."""
    parts = ["Agent satisfied request"]
    if user_message is not None:
        parts.append(f"user_message={user_message!r}")
    if context_id is not None:
        parts.append(f"context_id={context_id}")
    if task_id is not None:
        parts.append(f"task_id={task_id}")
    if response_preview is not None:
        preview = response_preview[:200] + "..." if len(response_preview) > 200 else response_preview
        parts.append(f"response_preview={preview!r}")
    _logger.bind(agent_success=True).info(" | ".join(parts))


# configure logger on import so other modules can `from .config import logger`
configure_logger()
logger = _logger