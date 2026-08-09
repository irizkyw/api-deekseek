"""
DeepSeek API Client Library

Provides a clean Python interface to DeepSeek's unofficial web chat API,
supporting free chats, thinking mode (DeepSeek-R1), web search, and image uploads.
"""

from .api import (
    DeepSeekAPI,
    AuthenticationError,
    RateLimitError,
    NetworkError,
    APIError,
    CloudflareError,
    DeepSeekError,
)
from .pow import DeepSeekPOW

__version__ = "1.0.0"
__all__ = [
    "DeepSeekAPI",
    "DeepSeekPOW",
    "AuthenticationError",
    "RateLimitError",
    "NetworkError",
    "APIError",
    "CloudflareError",
    "DeepSeekError",
]
