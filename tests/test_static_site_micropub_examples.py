from datetime import datetime, timezone

import pytest
from examples.static_site_micropub import (
    DjangoStorageStaticSiteHandler,
    GitBackedStaticSiteHandler,
    IndexedMediaHooksMixin,
    LocalFilesystemStaticSiteHandler,
    StaticSitePostMapper,
    slugify_micropub_properties,
)

from indieweb.handlers import MicropubMediaItem, MicropubMediaList


class DummyUser:
    pass


def test_static_site_mapper_uses_mp_slug_for_path_url_and_front_matter():
    mapper = StaticSitePostMapper(
        public_base_url="https://example.org/",
        content_dir="_posts",
        now=datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc),
    )

    document = mapper.build_document(
        {
            "name": ["Static site Micropub"],
            "content": ["A post body"],
            "category": ["indieweb", "static-site"],
            "mp-slug": ["Static Site / Micropub!"],
            "mp-channel": ["articles"],
            "mp-syndicate-to": ["https://social.example/@me"],
            "post-status": ["draft"],
            "published": ["2026-05-06T10:11:12+00:00"],
        }
    )

    assert document.path.as_posix() == "_posts/2026-05-06-static-site-micropub.md"
    assert document.url == "https://example.org/posts/2026/05/06/static-site-micropub/"
    assert document.front_matter["title"] == "Static site Micropub"
    assert document.front_matter["tags"] == ["indieweb", "static-site"]
    assert document.front_matter["status"] == "draft"
    assert document.front_matter["type"] == "article"
    assert document.front_matter["mp_channel"] == ["articles"]
    assert document.front_matter["mp_syndicate_to"] == ["https://social.example/@me"]
    assert document.front_matter["micropub"]["mp-slug"] == ["Static Site / Micropub!"]
    assert "A post body" in document.render_markdown()


def test_static_site_mapper_falls_back_to_note_slug_and_current_date():
    mapper = StaticSitePostMapper(
        public_base_url="https://example.org/blog",
        now=datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc),
    )

    document = mapper.build_document({"content": ["Hello, small note."]})

    assert document.path.as_posix() == "content/posts/2026-05-06-hello-small-note.md"
    assert document.url == "https://example.org/blog/posts/2026/05/06/hello-small-note/"
    assert document.front_matter["type"] == "note"


def test_static_site_mapper_marks_photo_posts_without_claiming_full_type_support():
    mapper = StaticSitePostMapper(
        public_base_url="https://example.org/",
        now=datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc),
    )

    document = mapper.build_document(
        {
            "content": ["A photo note"],
            "photo": ["https://example.org/media/photo.jpg"],
        }
    )

    assert document.front_matter["type"] == "photo"
    assert document.front_matter["photos"] == ["https://example.org/media/photo.jpg"]


def test_static_site_mapper_extracts_text_from_dict_property_values():
    mapper = StaticSitePostMapper(
        public_base_url="https://example.org/",
        now=datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc),
    )

    document = mapper.build_document(
        {
            "content": [{"html": "<p>Rendered body</p>", "value": "Rendered body"}],
            "category": [{"value": "indieweb"}],
            "photo": [{"value": "https://example.org/media/photo.jpg", "alt": "A photo"}],
            "mp-syndicate-to": [{"url": "https://social.example/@me"}],
        }
    )

    assert document.body == "<p>Rendered body</p>"
    assert document.front_matter["tags"] == ["indieweb"]
    assert document.front_matter["photos"] == ["https://example.org/media/photo.jpg"]
    assert document.front_matter["mp_syndicate_to"] == ["https://social.example/@me"]


def test_slugify_micropub_properties_has_safe_fallback():
    assert slugify_micropub_properties({"mp-slug": ["../../bad path"]}) == "bad-path"
    assert slugify_micropub_properties({"content": ["!!!"]}) == "post"


def test_local_filesystem_handler_writes_under_configured_root(tmp_path):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")

    entry = handler.create_entry(
        {
            "content": ["Filesystem body"],
            "mp-slug": ["filesystem-note"],
            "published": ["2026-05-06T00:00:00+00:00"],
        },
        DummyUser(),
    )

    stored_file = tmp_path / "content/posts/2026-05-06-filesystem-note.md"
    assert entry.url == "https://example.org/posts/2026/05/06/filesystem-note/"
    assert stored_file.exists()
    assert "Filesystem body" in stored_file.read_text(encoding="utf-8")


def test_local_filesystem_handler_rejects_slug_collisions(tmp_path):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    properties = {
        "content": ["Filesystem body"],
        "mp-slug": ["filesystem-note"],
        "published": ["2026-05-06T00:00:00+00:00"],
    }

    handler.create_entry(properties, DummyUser())

    with pytest.raises(FileExistsError, match="already exists"):
        handler.create_entry(properties, DummyUser())


def test_local_filesystem_handler_rejects_paths_outside_configured_root(tmp_path):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    handler.mapper = StaticSitePostMapper(public_base_url="https://example.org/", content_dir="../outside")

    with pytest.raises(ValueError, match="escaped"):
        handler.create_entry(
            {
                "content": ["Escape attempt"],
                "mp-slug": ["escape"],
                "published": ["2026-05-06T00:00:00+00:00"],
            },
            DummyUser(),
        )

    assert not (tmp_path.parent / "outside").exists()


class FakeStorage:
    def __init__(self):
        self.saved: dict[str, str] = {}

    def save(self, name, content):
        self.saved[name] = content.read().decode("utf-8")
        return name


def test_django_storage_handler_delegates_to_explicit_storage():
    storage = FakeStorage()
    handler = DjangoStorageStaticSiteHandler(storage=storage, public_base_url="https://example.org/")

    entry = handler.create_entry(
        {
            "content": ["Storage body"],
            "mp-slug": ["storage-note"],
            "published": ["2026-05-06T00:00:00+00:00"],
        },
        DummyUser(),
    )

    assert entry.url == "https://example.org/posts/2026/05/06/storage-note/"
    assert set(storage.saved) == {"content/posts/2026-05-06-storage-note.md"}
    assert "Storage body" in storage.saved["content/posts/2026-05-06-storage-note.md"]


class FakeGitStore:
    def __init__(self):
        self.calls = []

    def save_file(self, *, path, content, message):
        self.calls.append({"path": path, "content": content, "message": message})


def test_git_backed_handler_delegates_to_host_adapter_without_git_operations():
    store = FakeGitStore()
    handler = GitBackedStaticSiteHandler(store=store, public_base_url="https://example.org/")

    entry = handler.create_entry(
        {
            "content": ["Git body"],
            "mp-slug": ["git-note"],
            "published": ["2026-05-06T00:00:00+00:00"],
        },
        DummyUser(),
    )

    assert entry.url == "https://example.org/posts/2026/05/06/git-note/"
    assert len(store.calls) == 1
    assert store.calls[0]["path"] == "content/posts/2026-05-06-git-note.md"
    assert store.calls[0]["message"] == "Create Micropub post https://example.org/posts/2026/05/06/git-note/"
    assert "Git body" in store.calls[0]["content"]


class FakeMediaIndex:
    def __init__(self):
        self.item = MicropubMediaItem(
            url="https://example.org/media/photo.jpg",
            properties={"url": ["https://example.org/media/photo.jpg"], "name": ["photo.jpg"]},
        )
        self.deleted_urls = []

    def list_for_user(self, user, *, limit=None, offset=0, filter=None):
        return MicropubMediaList(items=[self.item], total=1)

    def get_for_user(self, url, user):
        if url == self.item.url:
            return self.item
        return None

    def delete_for_user(self, url, user):
        if url != self.item.url:
            return False
        self.deleted_urls.append(url)
        return True


class MediaHookExample(IndexedMediaHooksMixin):
    def __init__(self, media_index):
        self.media_index = media_index


def test_indexed_media_hooks_delegate_to_host_media_index():
    media_index = FakeMediaIndex()
    handler = MediaHookExample(media_index)
    user = DummyUser()

    media_list = handler.list_media(user, limit=10, offset=0, filter="photo")

    assert media_list.total == 1
    assert handler.get_media("https://example.org/media/photo.jpg", user) == media_index.item
    assert handler.delete_media("https://example.org/media/photo.jpg", user) is True
    assert media_index.deleted_urls == ["https://example.org/media/photo.jpg"]
