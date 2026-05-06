"""Static-site Micropub handler examples.

These examples are deliberately ordinary host-project code. They show how a
Django project can map Micropub properties to static-site files without making
django-indieweb own a content store, static-site generator, Git workflow, or
media index.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urljoin

from django.core.files.base import ContentFile

from indieweb.handlers import (
    MicropubContentHandler,
    MicropubEntry,
    MicropubEntryList,
    MicropubMediaItem,
    MicropubMediaList,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.core.files.storage import Storage


def _first_text(properties: dict[str, list[Any]], key: str, default: str = "") -> str:
    values = properties.get(key, [])
    if not values:
        return default
    value = values[0]
    return _text_value(value, default=default)


def _text_value(value: Any, *, default: str = "") -> str:
    """Return text for common Micropub values; serialize unrecognized dicts as JSON."""

    if value in (None, ""):
        return default
    if isinstance(value, dict):
        if "html" in value:
            return str(value["html"])
        if "value" in value:
            return str(value["value"])
        if "url" in value:
            return str(value["url"])
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


def _text_list(properties: dict[str, list[Any]], key: str) -> list[str]:
    return [text for value in properties.get(key, []) if (text := _text_value(value))]


def slugify_micropub_properties(properties: dict[str, list[Any]]) -> str:
    """Return a conservative slug from ``mp-slug``, title, content, or fallback text."""

    candidate = (
        _first_text(properties, "mp-slug")
        or _first_text(properties, "name")
        or _first_text(properties, "content")
        or "post"
    )
    normalized = unicodedata.normalize("NFKD", candidate).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:80].strip("-") or "post"


def infer_static_post_kind(properties: dict[str, list[Any]]) -> str:
    """Infer a small static-site post kind without pretending to cover every Micropub type."""

    if properties.get("photo"):
        return "photo"
    if _first_text(properties, "name"):
        return "article"
    return "note"


def _published_datetime(properties: dict[str, list[Any]], fallback: datetime) -> datetime:
    published = _first_text(properties, "published")
    if not published:
        return fallback
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return fallback


def _front_matter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


@dataclass(frozen=True)
class StaticPostDocument:
    """Rendered static-site post content plus the host path and public URL."""

    path: PurePosixPath
    url: str
    front_matter: dict[str, Any]
    body: str
    properties: dict[str, list[Any]]

    def render_markdown(self) -> str:
        """Render a simple Markdown document with YAML-compatible front matter."""

        front_matter_lines = [
            f"{key}: {_front_matter_value(value)}"
            for key, value in self.front_matter.items()
            if value not in (None, "", [], {})
        ]
        return "---\n" + "\n".join(front_matter_lines) + "\n---\n\n" + self.body.rstrip() + "\n"


class StaticSitePostMapper:
    """Map Micropub properties to a static-site path, URL, and front matter."""

    def __init__(
        self,
        *,
        public_base_url: str,
        content_dir: str = "content/posts",
        filename_pattern: str = "{year}-{month}-{day}-{slug}.md",
        url_pattern: str = "posts/{year}/{month}/{day}/{slug}/",
        now: datetime | None = None,
    ) -> None:
        self.public_base_url = public_base_url.rstrip("/") + "/"
        self.content_dir = PurePosixPath(content_dir)
        self.filename_pattern = filename_pattern
        self.url_pattern = url_pattern
        self.now = now

    def build_document(self, properties: dict[str, list[Any]]) -> StaticPostDocument:
        published = _published_datetime(properties, self.now or datetime.now(timezone.utc))
        slug = slugify_micropub_properties(properties)
        values = {
            "year": f"{published.year:04d}",
            "month": f"{published.month:02d}",
            "day": f"{published.day:02d}",
            "slug": slug,
        }
        filename = self.filename_pattern.format(**values)
        url_path = self.url_pattern.format(**values).lstrip("/")
        copied_properties = {key: list(value) for key, value in properties.items()}
        front_matter = {
            "title": _first_text(properties, "name"),
            "date": published.isoformat(),
            "tags": _text_list(properties, "category"),
            "status": _first_text(properties, "post-status", "published"),
            "type": infer_static_post_kind(properties),
            "photos": _text_list(properties, "photo"),
            "mp_slug": _first_text(properties, "mp-slug"),
            "mp_channel": _text_list(properties, "mp-channel"),
            "mp_syndicate_to": _text_list(properties, "mp-syndicate-to"),
            "micropub": copied_properties,
        }
        return StaticPostDocument(
            path=self.content_dir / filename,
            url=urljoin(self.public_base_url, url_path),
            front_matter=front_matter,
            body=_first_text(properties, "content"),
            properties=copied_properties,
        )


class StaticSiteMicropubHandler(MicropubContentHandler):
    """Base example for handlers that create static-site documents."""

    def __init__(self, *, mapper: StaticSitePostMapper) -> None:
        self.mapper = mapper

    def create_entry(self, properties: dict[str, list[Any]], user: AbstractBaseUser) -> MicropubEntry:
        document = self.mapper.build_document(properties)
        self.save_document(document, user)
        return MicropubEntry(url=document.url, properties=document.properties)

    def save_document(self, document: StaticPostDocument, user: AbstractBaseUser) -> None:
        """Persist ``document`` using a host-owned storage strategy."""

        raise NotImplementedError

    def get_entry(self, url: str, user: AbstractBaseUser) -> MicropubEntry | None:
        return None

    def list_entries(
        self,
        user: AbstractBaseUser,
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubEntryList | None:
        return None

    def update_entry(self, url: str, updates: dict[str, Any], user: AbstractBaseUser) -> MicropubEntry:
        raise NotImplementedError("Static-site updates require a host-owned index and rewrite policy")

    def delete_entry(self, url: str, user: AbstractBaseUser) -> None:
        raise NotImplementedError("Static-site deletes require a host-owned URL-to-path policy")

    def undelete_entry(self, url: str, user: AbstractBaseUser) -> MicropubEntry:
        raise NotImplementedError("Static-site undeletes require host-owned tombstone or version history")


class LocalFilesystemStaticSiteHandler(StaticSiteMicropubHandler):
    """Example handler that writes new Markdown files under one configured root."""

    def __init__(self, *, content_root: Path | str, public_base_url: str) -> None:
        super().__init__(mapper=StaticSitePostMapper(public_base_url=public_base_url))
        self.content_root = Path(content_root).resolve()

    def _target_path(self, document: StaticPostDocument) -> Path:
        target = (self.content_root / document.path.as_posix()).resolve()
        if not target.is_relative_to(self.content_root):
            raise ValueError("Static-site document path escaped the configured content root")
        return target

    def save_document(self, document: StaticPostDocument, user: AbstractBaseUser) -> None:
        target = self._target_path(document)
        if target.exists():
            raise FileExistsError(f"Static-site document already exists: {document.path.as_posix()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document.render_markdown(), encoding="utf-8")


class DjangoStorageStaticSiteHandler(StaticSiteMicropubHandler):
    """Example handler that writes post files through an explicit Django storage."""

    def __init__(self, *, storage: Storage, public_base_url: str) -> None:
        super().__init__(mapper=StaticSitePostMapper(public_base_url=public_base_url))
        self.storage = storage

    def save_document(self, document: StaticPostDocument, user: AbstractBaseUser) -> None:
        expected_name = document.path.as_posix()
        saved_name = self.storage.save(expected_name, ContentFile(document.render_markdown().encode("utf-8")))
        if saved_name != expected_name:
            raise ValueError("Storage changed the post path; host code should resolve slug collisions explicitly")


class GitBackedPostStore(Protocol):
    """Host-owned Git adapter boundary; implementations may use local Git, GitHub, GitLab, etc."""

    def save_file(self, *, path: str, content: str, message: str) -> None:
        """Persist a file through the host's repository workflow."""


class GitBackedStaticSiteHandler(StaticSiteMicropubHandler):
    """Example handler that delegates repository writes to host-owned adapter code."""

    def __init__(self, *, store: GitBackedPostStore, public_base_url: str) -> None:
        super().__init__(mapper=StaticSitePostMapper(public_base_url=public_base_url))
        self.store = store

    def save_document(self, document: StaticPostDocument, user: AbstractBaseUser) -> None:
        self.store.save_file(
            path=document.path.as_posix(),
            content=document.render_markdown(),
            message=f"Create Micropub post {document.url}",
        )


class HostMediaIndex(Protocol):
    """Host-owned media index used by the optional Micropub media hooks."""

    def list_for_user(
        self,
        user: AbstractBaseUser,
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubMediaList:
        """Return media records the user is allowed to see."""

    def get_for_user(self, url: str, user: AbstractBaseUser) -> MicropubMediaItem | None:
        """Return one recognized media record."""

    def delete_for_user(self, url: str, user: AbstractBaseUser) -> bool:
        """Delete one recognized media record according to host policy."""


class IndexedMediaHooksMixin:
    """
    Mixin that shows media hook delegation to a durable host-owned index.

    Assign ``self.media_index`` in the concrete handler's ``__init__`` before
    these hooks can be used.
    """

    media_index: HostMediaIndex

    def list_media(
        self,
        user: AbstractBaseUser,
        *,
        limit: int | None = None,
        offset: int = 0,
        filter: str | None = None,
    ) -> MicropubMediaList:
        return self.media_index.list_for_user(user, limit=limit, offset=offset, filter=filter)

    def get_media(self, url: str, user: AbstractBaseUser) -> MicropubMediaItem | None:
        return self.media_index.get_for_user(url, user)

    def delete_media(self, url: str, user: AbstractBaseUser) -> bool:
        return self.media_index.delete_for_user(url, user)
