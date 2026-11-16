import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
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


@pytest.mark.parametrize("swap_root", [False, True])
@pytest.mark.parametrize("link_fails", [False, True])
def test_local_publication_and_cleanup_keep_held_directory(tmp_path, monkeypatch, swap_root, link_fails):
    root = tmp_path / "site"
    handler = LocalFilesystemStaticSiteHandler(content_root=root, public_base_url="https://example.org/")
    document = handler.mapper.build_document({"mp-slug": ["held"], "content": ["Synthetic post"]})
    outside = tmp_path / "outside"
    outside_posts = outside / document.path.parent if swap_root else outside
    outside_posts.mkdir(parents=True)
    displaced = tmp_path / "displaced"
    named = root if swap_root else root / document.path.parent
    held_posts = displaced / document.path.parent if swap_root else displaced
    link = os.link
    outside_stage = None

    def swap_then_link(source, target, **kwargs):
        nonlocal outside_stage
        named.rename(displaced)
        named.symlink_to(outside, target_is_directory=True)
        outside_stage = outside_posts / Path(source).name
        outside_stage.write_text("Outside sentinel")
        if link_fails:
            raise OSError("Synthetic link failure")
        return link(source, target, **kwargs)

    monkeypatch.setattr("examples.static_site_micropub.os.link", swap_then_link)
    if link_fails:
        with pytest.raises(OSError, match="Synthetic link failure"):
            handler.save_document(document, DummyUser())
    else:
        handler.save_document(document, DummyUser())
        assert (held_posts / document.path.name).read_text() == document.render_markdown()
    assert outside_stage.read_text() == "Outside sentinel"
    assert list(outside_posts.iterdir()) == [outside_stage]
    assert not list(held_posts.glob(".micropub-*"))


def test_local_publication_refuses_symlink_during_descent(tmp_path, monkeypatch):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path / "site", public_base_url="https://example.org/")
    outside = tmp_path / "outside"
    outside.mkdir()
    open_file = os.open

    def swap_before_open(path, flags, *args, **kwargs):
        if path == "posts":
            parent = handler.content_root / "content"
            (parent / "posts").rmdir()
            (parent / "posts").symlink_to(outside, target_is_directory=True)
        return open_file(path, flags, *args, **kwargs)

    monkeypatch.setattr("examples.static_site_micropub.os.open", swap_before_open)
    with pytest.raises(OSError):
        handler.create_entry({"content": ["Synthetic post"]}, DummyUser())
    assert list(outside.iterdir()) == []


def test_local_publication_syncs_file_then_link_cleanup_and_all_directories(tmp_path, monkeypatch):
    handler = LocalFilesystemStaticSiteHandler(
        content_root=tmp_path / "new/site", public_base_url="https://example.org/"
    )
    document = handler.mapper.build_document({"mp-slug": ["durable"], "content": ["Synthetic durable post"]})
    target = handler.content_root / document.path
    events = []
    directories = []
    synced_directories = []
    open_file, sync, link, unlink = os.open, os.fsync, os.link, os.unlink

    # Search-only descriptors for traverse-only ancestors of tmp_path are never synced.
    search_only = (getattr(os, "O_PATH", 0) or getattr(os, "O_SEARCH", 0)) & ~os.O_DIRECTORY

    def track_open(path, flags, *args, **kwargs):
        fd = open_file(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY and not flags & search_only:
            directories.append(fd)
        return fd

    def track_sync(fd):
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        events.append("directory" if is_directory else "file")
        if is_directory:
            assert target.read_text() == document.render_markdown()
            assert not list(target.parent.glob(".micropub-*"))
            synced_directories.append(fd)
        sync(fd)

    def track_link(*args, **kwargs):
        events.append("link")
        return link(*args, **kwargs)

    def track_unlink(*args, **kwargs):
        events.append("unlink")
        return unlink(*args, **kwargs)

    monkeypatch.setattr("examples.static_site_micropub.os.open", track_open)
    monkeypatch.setattr("examples.static_site_micropub.os.fsync", track_sync)
    monkeypatch.setattr("examples.static_site_micropub.os.link", track_link)
    monkeypatch.setattr("examples.static_site_micropub.os.unlink", track_unlink)
    handler.save_document(document, DummyUser())
    assert events[:4] == ["file", "link", "unlink", "directory"]
    assert directories  # includes newly created root and nested post parents
    assert synced_directories == list(reversed(directories))
    for fd in directories:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("failure", ["file", "leaf", "ancestor", "cleanup"])
def test_local_publication_failure_distinguishes_safe_retry_and_uncertainty(tmp_path, monkeypatch, failure):
    handler = LocalFilesystemStaticSiteHandler(content_root=tmp_path, public_base_url="https://example.org/")
    document = handler.mapper.build_document({"mp-slug": ["uncertain"], "content": ["Synthetic retained post"]})
    target = tmp_path / document.path
    sync, unlink = os.fsync, os.unlink
    synced_directories = []

    def fail_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            synced_directories.append(fd)
            if failure == "leaf" or (failure == "ancestor" and len(synced_directories) == 2):
                raise OSError("Synthetic directory sync failure")
        elif failure == "file":
            raise OSError("Synthetic file sync failure")
        sync(fd)

    def fail_cleanup(*args, **kwargs):
        if failure == "cleanup":
            raise OSError("Synthetic cleanup failure")
        return unlink(*args, **kwargs)

    monkeypatch.setattr("examples.static_site_micropub.os.fsync", fail_sync)
    monkeypatch.setattr("examples.static_site_micropub.os.unlink", fail_cleanup)
    if failure == "file":
        with pytest.raises(OSError, match="Synthetic file sync failure"):
            handler.save_document(document, DummyUser())
        assert not target.exists()
        # This failure is safe to retry once storage is healthy.
        monkeypatch.setattr("examples.static_site_micropub.os.fsync", sync)
        handler.save_document(document, DummyUser())
    else:
        with pytest.raises(RuntimeError, match="publication.*uncertain.*inspect.*retry") as caught:
            handler.save_document(document, DummyUser())
        assert isinstance(caught.value.__cause__, OSError)
        assert document.path.as_posix() in str(caught.value)
        assert target.read_text() == document.render_markdown()
        monkeypatch.setattr("examples.static_site_micropub.os.fsync", sync)
        monkeypatch.setattr("examples.static_site_micropub.os.unlink", unlink)
        with pytest.raises(FileExistsError):
            handler.save_document(document, DummyUser())
    assert target.read_text() == document.render_markdown()
    stages = list(target.parent.glob(".micropub-*"))
    assert len(stages) == (1 if failure == "cleanup" else 0)
    for fd in synced_directories:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions enforced for the user")
@pytest.mark.parametrize("root_exists", [True, False])
def test_local_publication_descends_through_traverse_only_ancestor(tmp_path, monkeypatch, root_exists):
    traverse_only = tmp_path / "home"
    root = traverse_only / "site"
    root.mkdir(parents=True) if root_exists else traverse_only.mkdir()
    handler = LocalFilesystemStaticSiteHandler(content_root=root, public_base_url="https://example.org/")
    document = handler.mapper.build_document({"mp-slug": ["traverse"], "content": ["Synthetic traverse post"]})
    sync = os.fsync
    synced = []

    def track_sync(fd):
        synced.append(os.fstat(fd).st_ino)
        sync(fd)

    monkeypatch.setattr("examples.static_site_micropub.os.fsync", track_sync)
    traverse_only.chmod(0o311)
    try:
        handler.save_document(document, DummyUser())
    finally:
        traverse_only.chmod(0o755)
    assert (root / document.path).read_text() == document.render_markdown()
    assert root.stat().st_ino in synced
    assert (root / document.path).parent.stat().st_ino in synced
    assert traverse_only.stat().st_ino not in synced


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
