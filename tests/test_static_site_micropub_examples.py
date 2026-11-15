import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from django.core.files.storage import FileSystemStorage
from examples.static_site_micropub import (
    DjangoStorageStaticSiteHandler,
    GitBackedStaticSiteHandler,
    IndexedMediaHooksMixin,
    LocalFilesystemStaticSiteHandler,
    StaticPostDocument,
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
        now=datetime(2026, 5, 6, 8, 30, tzinfo=UTC),
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
        now=datetime(2026, 5, 6, 8, 30, tzinfo=UTC),
    )

    document = mapper.build_document({"content": ["Hello, small note."]})

    assert document.path.as_posix() == "content/posts/2026-05-06-hello-small-note.md"
    assert document.url == "https://example.org/blog/posts/2026/05/06/hello-small-note/"
    assert document.front_matter["type"] == "note"


def test_static_site_mapper_marks_photo_posts_without_claiming_full_type_support():
    mapper = StaticSitePostMapper(
        public_base_url="https://example.org/",
        now=datetime(2026, 5, 6, 8, 30, tzinfo=UTC),
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
        now=datetime(2026, 5, 6, 8, 30, tzinfo=UTC),
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


def test_local_filesystem_published_post_honours_the_umask(tmp_path):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    previous = os.umask(0o022)
    try:
        handler.create_entry(
            {"content": ["Mode body"], "mp-slug": ["mode-note"], "published": ["2026-05-06T00:00:00+00:00"]},
            DummyUser(),
        )
        assert os.umask(0o022) == 0o022  # the handler never changes the process umask
    finally:
        os.umask(previous)
    stored_file = tmp_path / "content/posts/2026-05-06-mode-note.md"
    assert stat.S_IMODE(stored_file.stat().st_mode) == 0o644
    assert not list(stored_file.parent.glob(".micropub-*"))


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


def test_local_filesystem_concurrent_creates_publish_one_complete_post(tmp_path, monkeypatch):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    documents = [
        handler.mapper.build_document({"mp-slug": ["same"], "published": ["2026-11-15"], "content": [body * 10000]})
        for body in ("First synthetic body", "Second synthetic body")
    ]
    render = StaticPostDocument.render_markdown
    rendezvous = Barrier(2)

    def synchronized_render(document):
        rendezvous.wait(timeout=10)
        return render(document)

    monkeypatch.setattr(StaticPostDocument, "render_markdown", synchronized_render)

    def publish(document):
        try:
            handler.save_document(document, DummyUser())
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, documents))

    assert sorted(outcomes) == [False, True]
    target = tmp_path / documents[0].path
    winner = documents[outcomes.index(True)]
    assert target.read_text(encoding="utf-8") == render(winner)
    assert list(target.parent.iterdir()) == [target]


def test_local_filesystem_interrupted_stage_never_publishes_partial_post(tmp_path, monkeypatch):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    document = handler.mapper.build_document({"mp-slug": ["interrupted"], "content": ["Synthetic body"]})
    target = tmp_path / document.path

    def interrupt_sync(fd):
        assert not target.exists()
        staged = list(target.parent.iterdir())
        assert len(staged) == 1
        assert staged[0].read_text(encoding="utf-8") == document.render_markdown()
        raise KeyboardInterrupt("Interrupted before publication")

    monkeypatch.setattr("examples.static_site_micropub.os.fsync", interrupt_sync)
    with pytest.raises(KeyboardInterrupt, match="Interrupted"):
        handler.save_document(document, DummyUser())

    assert not target.exists()
    assert list(target.parent.iterdir()) == []


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


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_django_storage_renamed_object_is_compensated_without_deleting_target(cleanup_fails):
    target = "content/posts/2026-11-15-same.md"
    alternate = "content/posts/2026-11-15-same_owned.md"

    class RenamingStorage(FakeStorage):
        def __init__(self):
            super().__init__()
            self.saved[target] = "Original complete post"
            self.deleted = []

        def save(self, name, content):
            assert name == target
            self.saved[alternate] = content.read().decode("utf-8")
            return alternate

        def delete(self, name):
            self.deleted.append(name)
            if cleanup_fails:
                raise OSError("Synthetic cleanup failure")
            del self.saved[name]

    storage = RenamingStorage()
    handler = DjangoStorageStaticSiteHandler(storage=storage, public_base_url="https://example.org/")
    error_type = RuntimeError if cleanup_fails else ValueError
    message = "cleanup.*uncertain" if cleanup_fails else "Storage changed"
    with pytest.raises(error_type, match=message) as caught:
        handler.create_entry(
            {"mp-slug": ["same"], "published": ["2026-11-15"], "content": ["New synthetic post"]},
            DummyUser(),
        )

    assert storage.saved[target] == "Original complete post"
    assert storage.deleted == [alternate]
    assert (alternate in storage.saved) is cleanup_fails
    if cleanup_fails:
        assert alternate in str(caught.value)
        assert isinstance(caught.value.__cause__, OSError)


def test_django_storage_collision_compensation_with_real_local_storage(tmp_path):
    storage = FileSystemStorage(location=tmp_path)
    handler = DjangoStorageStaticSiteHandler(storage=storage, public_base_url="https://example.org/")
    document = handler.mapper.build_document({"mp-slug": ["local-storage"], "content": ["Original synthetic post"]})
    handler.save_document(document, DummyUser())
    original = (tmp_path / document.path).read_bytes()

    with pytest.raises(ValueError, match="Storage changed"):
        handler.create_entry({**document.properties, "content": ["Rejected synthetic post"]}, DummyUser())

    assert (tmp_path / document.path).read_bytes() == original
    assert list((tmp_path / document.path).parent.iterdir()) == [tmp_path / document.path]


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
