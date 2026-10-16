"""Registered startup/setup adapters; separate from transcript and engine providers."""
from api.services import cursor_integration

LOCAL = {cursor_integration.ID: cursor_integration}
