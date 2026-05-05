"""
Micropub content handler interface and implementations.

This module provides the interface for handling Micropub content operations
and includes basic implementations for testing and development.
"""

import json
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


@dataclass
class MicropubEntryList:
    """Represents a page of Micropub entries returned by a content handler."""

    entries: list[MicropubEntry]
    total: int | None = None


@dataclass
class MicropubMediaItem:
    """Represents a host-owned Micropub media item."""

    url: str
    properties: dict[str, list[Any]]


@dataclass
class MicropubMediaList:
    """Represents a page of host-owned Micropub media items."""

    items: list[MicropubMediaItem]
    total: int | None = None


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

    def list_entries(
        self,
        user: "AbstractBaseUser",
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubEntryList | None:
        """
        Return a page of editable/source entries for ``GET ?q=source`` list mode.

        The default ``None`` return means this optional capability is unsupported by
        the handler. Implementations that can enumerate host-owned content should
        honor ``limit``, ``offset``, and ``filter`` and return a ``MicropubEntryList``.
        ``filter`` is ``None`` when the client omitted it or submitted an empty value.
        ``total`` should only be set when it is known accurately after filtering and
        before pagination.
        """
        return None

    def list_media(
        self,
        user: "AbstractBaseUser",
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubMediaList | None:
        """
        Return a page of host-owned media for ``GET /indieweb/media/?q=source``.

        The default ``None`` return means media enumeration is unsupported by the
        handler. django-indieweb does not maintain a built-in media index; host
        applications that can list uploaded media should implement this hook and
        enforce their own ownership policy before returning results. Return an
        empty ``MicropubMediaList(items=[])`` for "no items"; return ``None`` only
        when list mode is unsupported. Override this method on the handler
        subclass; instance-level assignments are not detected by the view.
        """
        return None

    def get_media(self, url: str, user: "AbstractBaseUser") -> MicropubMediaItem | None:
        """
        Return metadata for one host-owned media URL.

        The default ``None`` return means the handler either does not support
        media lookup or does not recognize the submitted URL as host-owned.
        Override this method on the handler subclass; instance-level assignments
        are not detected by the view.
        """
        return None

    def delete_media(self, url: str, user: "AbstractBaseUser") -> bool | None:
        """
        Delete one host-owned media URL when supported.

        Return ``True`` after deleting the media item, ``False`` to reject a
        recognized-but-not-deleted URL, or ``None`` when media deletion is
        unsupported or the URL is unknown. django-indieweb never infers storage
        paths from submitted URLs for this operation. Override this method on the
        handler subclass; instance-level assignments are not detected by the view.
        """
        return None

    def get_config(self, user: "AbstractBaseUser") -> dict[str, Any]:
        """
        Get Micropub configuration.

        Returns configuration including supported properties, syndication targets, etc.
        """
        return {
            "media-endpoint": None,
            "syndicate-to": [],
            "categories": [],
            "channels": [],
            "post-types": [
                {"type": "note", "name": "Note", "properties": ["content"]},
                {"type": "article", "name": "Article", "properties": ["name", "content"]},
                {"type": "photo", "name": "Photo", "properties": ["photo", "content", "category"]},
                {"type": "audio", "name": "Audio", "properties": ["audio", "content", "category"]},
                {"type": "video", "name": "Video", "properties": ["video", "content", "category"]},
                {"type": "reply", "name": "Reply", "properties": ["in-reply-to", "content"]},
                {"type": "bookmark", "name": "Bookmark", "properties": ["bookmark-of", "name", "content"]},
                {"type": "like", "name": "Like", "properties": ["like-of"]},
                {"type": "repost", "name": "Repost", "properties": ["repost-of"]},
                {
                    "type": "event",
                    "name": "Event",
                    "properties": [
                        "name",
                        "summary",
                        "description",
                        "start",
                        "end",
                        "location",
                        "category",
                        "url",
                        "published",
                    ],
                },
                {"type": "rsvp", "name": "RSVP", "properties": ["rsvp", "in-reply-to", "name", "content"]},
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

    @staticmethod
    def _entry_filter_matches(entry: MicropubEntry, needle: str) -> bool:
        item = {
            "type": entry.type,
            "properties": {
                **entry.properties,
                "url": entry.properties.get("url", [entry.url]),
            },
        }
        return needle in json.dumps(item, sort_keys=True).lower()

    def list_entries(
        self,
        user: "AbstractBaseUser",
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubEntryList:
        entries = list(self.entries.values())
        if filter:
            needle = filter.lower()
            entries = [entry for entry in entries if self._entry_filter_matches(entry, needle)]
        total = len(entries)
        if offset:
            entries = entries[offset:]
        if limit is not None:
            entries = entries[:limit]
        return MicropubEntryList(entries=entries, total=total)


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
