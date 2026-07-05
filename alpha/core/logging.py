import sys

from loguru import logger


def configure_logging() -> None:
    """Configure application logging."""

    logger.remove()

    logger.add(
        sys.stdout,
        format=(
            "<green>{time}</green> | <level>{level}</level> | <level>{message}</level>"
        ),
        level="INFO",
    )
