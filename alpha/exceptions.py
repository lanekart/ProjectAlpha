"""
Domain exceptions for Project Alpha.

Higher layers should catch these instead of generic Exception.
"""


class ProjectAlphaError(Exception):
    """Base exception for all Project Alpha errors."""


class DownloadError(ProjectAlphaError):
    """Base class for download-related failures."""


class BhavcopyNotFoundError(DownloadError):
    """Raised when a bhavcopy cannot be located."""


class ExtractionError(ProjectAlphaError):
    """Raised when archive extraction fails."""


class ValidationError(ProjectAlphaError):
    """Raised when ingested market data is invalid."""
