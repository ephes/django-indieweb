"""
Micropub content handler interface and implementations.

This module provides the interface for handling Micropub content operations
and includes basic implementations for testing and development.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


@dataclass
class MicropubEntry:
    """Represents a Micropub entry with its URL and properties."""

    url: str
    properties: dict[str, list[Any]]
    type: list[str] = field(default_factory=lambda: ["h-entry"])

    def get_property(self, key: str, default: Any = None) -> Any:
        """Get the first value of a property."""
        values = self.properties.get(key, [])
        return values[0] if values else default

    def get_properties(self, key: str) -> list[Any]:
        """Get all values of a property."""
        return self.properties.get(key, [])


class MicropubContentHandler(ABC):
    """
    Abstract base class for Micropub content handlers.

    Implementations should handle the storage and retrieval of content
    created through the Micropub API.
    """

    @abstractmethod
    def create_entry(self, properties: dict[str, list[Any]], user: "AbstractBaseUser") -> MicropubEntry:
        """
        Create a new entry from Micropub properties.

        Args:
            properties: Micropub properties in normalized format
            user: The authenticated user creating the entry

        Returns:
            MicropubEntry with the URL of the created content
        """
        pass

    @abstractmethod
    def update_entry(self, url: str, updates: dict[str, Any], user: "AbstractBaseUser") -> MicropubEntry:
        """
        Update an existing entry.

        Args:
            url: The URL of the entry to update
            updates: Dictionary with add/replace/delete operations
            user: The authenticated user

        Returns:
            Updated MicropubEntry

        Raises:
            ValueError: If the entry doesn't exist or user lacks permission
        """
        pass

    @abstractmethod
    def delete_entry(self, url: str, user: "AbstractBaseUser") -> None:
        """
        Delete an entry.

        Args:
            url: The URL of the entry to delete
            user: The authenticated user

        Raises:
            ValueError: If the entry doesn't exist or user lacks permission
        """
        pass

    @abstractmethod
    def undelete_entry(self, url: str, user: "AbstractBaseUser") -> MicropubEntry:
        """
        Restore a deleted entry.

        Args:
            url: The URL of the entry to restore
            user: The authenticated user

        Returns:
            Restored MicropubEntry

        Raises:
            ValueError: If the entry doesn't exist or user lacks permission
        """
        pass

    @abstractmethod
    def get_entry(self, url: str, user: "AbstractBaseUser") -> MicropubEntry | None:
        """
        Retrieve an entry by URL.

        Args:
            url: The URL of the entry
            user: The authenticated user

        Returns:
            MicropubEntry if found and user has permission, None otherwise
        """
        pass

    def get_config(self, user: "AbstractBaseUser") -> dict[str, Any]:
        """
        Get Micropub configuration.

        Returns configuration including supported properties, syndication targets, etc.
        """
        return {
            "media-endpoint": None,
            "syndicate-to": [],
            "post-types": [
                {"type": "note", "name": "Note", "properties": ["content"]},
                {"type": "article", "name": "Article", "properties": ["name", "content"]},
            ],
        }


class InMemoryMicropubHandler(MicropubContentHandler):
    """
    Simple in-memory implementation for testing.

    Stores entries in memory, useful for development and testing.
    """

    def __init__(self) -> None:
        self.entries: dict[str, MicropubEntry] = {}
        self.deleted_entries: dict[str, MicropubEntry] = {}
        self.counter = 0

    def create_entry(self, properties: dict[str, list[Any]], user: "AbstractBaseUser") -> MicropubEntry:
        self.counter += 1
        url = f"/entries/{self.counter}/"

        # Ensure properties are in list format
        normalized_props = {}
        for key, value in properties.items():
            if not isinstance(value, list):
                normalized_props[key] = [value]
            else:
                normalized_props[key] = value

        entry = MicropubEntry(url=url, properties=normalized_props)
        self.entries[url] = entry
        return entry

    def _apply_replace(self, entry: MicropubEntry, replacements: dict[str, Any]) -> None:
        """Apply replace operations to an entry."""
        for key, values in replacements.items():
            if not isinstance(values, list):
                values = [values]
            entry.properties[key] = values

    def _apply_add(self, entry: MicropubEntry, additions: dict[str, Any]) -> None:
        """Apply add operations to an entry."""
        for key, values in additions.items():
            if not isinstance(values, list):
                values = [values]
            if key not in entry.properties:
                entry.properties[key] = []
            entry.properties[key].extend(values)

    def _apply_delete_list(self, entry: MicropubEntry, deletions: list[str]) -> None:
        """Delete entire properties from an entry."""
        for key in deletions:
            entry.properties.pop(key, None)

    def _apply_delete_dict(self, entry: MicropubEntry, deletions: dict[str, Any]) -> None:
        """Delete specific values from properties."""
        for key, values in deletions.items():
            if key in entry.properties:
                if not isinstance(values, list):
                    values = [values]
                for value in values:
                    if value in entry.properties[key]:
                        entry.properties[key].remove(value)
                if not entry.properties[key]:
                    del entry.properties[key]

    def update_entry(self, url: str, updates: dict[str, Any], user: "AbstractBaseUser") -> MicropubEntry:
        if url not in self.entries:
            raise ValueError(f"Entry not found: {url}")

        entry = self.entries[url]

        # Handle replace operations
        if "replace" in updates:
            self._apply_replace(entry, updates["replace"])

        # Handle add operations
        if "add" in updates:
            self._apply_add(entry, updates["add"])

        # Handle delete operations
        if "delete" in updates:
            if isinstance(updates["delete"], list):
                self._apply_delete_list(entry, updates["delete"])
            elif isinstance(updates["delete"], dict):
                self._apply_delete_dict(entry, updates["delete"])

        return entry

    def delete_entry(self, url: str, user: "AbstractBaseUser") -> None:
        if url not in self.entries:
            raise ValueError(f"Entry not found: {url}")

        self.deleted_entries[url] = self.entries.pop(url)

    def undelete_entry(self, url: str, user: "AbstractBaseUser") -> MicropubEntry:
        if url not in self.deleted_entries:
            raise ValueError(f"Deleted entry not found: {url}")

        entry = self.deleted_entries.pop(url)
        self.entries[url] = entry
        return entry

    def get_entry(self, url: str, user: "AbstractBaseUser") -> MicropubEntry | None:
        return self.entries.get(url)


def get_micropub_handler() -> MicropubContentHandler:
    """
    Get the configured Micropub content handler.

    This function loads the handler specified in Django settings,
    or returns a default in-memory handler if none is configured.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    handler_path = getattr(settings, "INDIEWEB_MICROPUB_HANDLER", None)

    if handler_path:
        handler_class = import_string(handler_path)
        handler_instance: MicropubContentHandler = handler_class()
        return handler_instance
    else:
        # Return in-memory handler as default
        return InMemoryMicropubHandler()
