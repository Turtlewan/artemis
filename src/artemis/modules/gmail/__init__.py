"""Read-only Gmail connector module."""

from .cache import CachedMessage, GmailReadCache
from .client import (
    GMAIL_READONLY_SCOPE,
    SIGNAL_CATEGORIES,
    FakeGmailApi,
    GmailApiPort,
    GmailClient,
    MailCategory,
    categorize,
    is_signal,
)
from .module import build_gmail_manifest, register_gmail_scope
from .sync import GmailSync

__all__ = [
    "GMAIL_READONLY_SCOPE",
    "SIGNAL_CATEGORIES",
    "CachedMessage",
    "FakeGmailApi",
    "GmailApiPort",
    "GmailClient",
    "GmailReadCache",
    "GmailSync",
    "MailCategory",
    "build_gmail_manifest",
    "categorize",
    "is_signal",
    "register_gmail_scope",
]
