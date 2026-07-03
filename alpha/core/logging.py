from loguru import logger
import sys


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time}</green> | <level>{level}</level> | <level>{message}</level>",
        level="INFO",
    )