import sys
from types import ModuleType

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test.utils import isolate_apps
from django.utils.module_loading import import_string

from indieweb.models import Webmention
from tests.doc_examples import doc_block


@pytest.fixture
def blog_model(transactional_db, monkeypatch):
    with isolate_apps():

        class BlogPost(models.Model):
            author = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
            slug = models.SlugField(unique=True, default="synthetic-post")
            title = models.CharField(max_length=100)
            content = models.TextField()
            status = models.CharField(max_length=20)
            created = models.DateTimeField(auto_now_add=True)

            class Meta:
                app_label = "synthetic_docs"

            def __str__(self):
                return self.title

            def get_absolute_url(self):
                return f"/blog/{self.slug}/"

        module = ModuleType("myapp.models")
        module.BlogPost = BlogPost
        monkeypatch.setitem(sys.modules, "myapp", ModuleType("myapp"))
        monkeypatch.setitem(sys.modules, "myapp.models", module)
        with connection.schema_editor() as editor:
            editor.create_model(BlogPost)
        try:
            yield BlogPost
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(BlogPost)


@pytest.fixture
def load_adapter(monkeypatch):
    def load(page, marker, name):
        module = ModuleType("synthetic_doc_adapter")
        exec(doc_block(page, marker), module.__dict__)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        return import_string(f"{module.__name__}.{name}")()

    return load


@pytest.fixture
def handler(blog_model, load_adapter):
    return load_adapter("micropub.rst", "class BlogPostMicropubHandler", "BlogPostMicropubHandler")


@pytest.fixture
def owner(transactional_db):
    return get_user_model().objects.create_user(username="synthetic-owner")


def test_documented_handler_owned_lifecycle(handler, blog_model, owner):
    entry = handler.create_entry({"content": ["before"], "name": ["title"]}, owner)
    assert entry.url == "/blog/synthetic-post/"
    assert blog_model.objects.get().author == owner
    assert handler.get_entry(entry.url, owner).properties["content"] == ["before"]
    absolute = handler.public_origin + entry.url
    assert handler.get_entry(absolute, owner).url == entry.url
    updated = handler.update_entry(absolute, {"replace": {"content": ["after"], "name": ["new"]}}, owner)
    assert updated.properties["content"] == ["after"]
    assert updated.properties["name"] == ["new"]
    with pytest.raises(NotImplementedError):
        handler.undelete_entry(entry.url, owner)
    handler.delete_entry(entry.url, owner)
    assert not blog_model.objects.exists()
    assert handler.get_entry(entry.url, owner) is None
    with pytest.raises(ValueError):
        handler.delete_entry(entry.url, owner)


@pytest.mark.parametrize(
    "url",
    [
        "https://foreign.example/blog/synthetic-post/",
        "http://blog.example/blog/synthetic-post/",
        "//blog.example/blog/synthetic-post/",
        "/other/synthetic-post/",
        "/blog/synthetic-post",
        "/blog/synthetic-post/?edit=1",
        "/blog/synthetic-post/#section",
        "/blog/%73ynthetic-post/",
        "/blog/../synthetic-post/",
        "/blog/synthetic-post/extra/",
        "https://[broken",
        "\n/blog/synthetic-post/",
    ],
)
def test_documented_handler_rejects_noncanonical_urls(handler, blog_model, owner, url):
    handler.create_entry({"content": ["unchanged"]}, owner)
    assert handler.get_entry(url, owner) is None
    with pytest.raises(ValueError):
        handler.update_entry(url, {"replace": {"content": ["changed"]}}, owner)
    with pytest.raises(ValueError):
        handler.delete_entry(url, owner)
    assert blog_model.objects.get().content == "unchanged"


def test_documented_handler_rejects_foreign_owner(handler, blog_model, owner):
    entry = handler.create_entry({"content": ["private"]}, owner)
    foreign = get_user_model().objects.create_user(username="synthetic-foreign")
    assert handler.get_entry(entry.url, foreign) is None
    with pytest.raises(ValueError):
        handler.update_entry(entry.url, {"replace": {"content": ["changed"]}}, foreign)
    with pytest.raises(ValueError):
        handler.delete_entry(entry.url, foreign)
    assert blog_model.objects.get().content == "private"


def test_documented_url_adapter_imports_and_implements_interface(blog_model, owner, load_adapter):
    resolver = load_adapter("webmention.rst", "class MyURLResolver", "MyURLResolver")
    post = blog_model.objects.create(author=owner, title="Synthetic", content="text")
    assert resolver.resolve("https://blog.example/blog/synthetic-post/") == post
    assert resolver.resolve("https://blog.example/blog/missing/") is None
    assert resolver.resolve("https://blog.example/other/") is None
    assert resolver.get_absolute_url(post) == post.get_absolute_url()
    assert resolver.get_absolute_url(object()) == ""


@pytest.mark.parametrize("content,is_spam", [("Synthetic lottery promotion", True), ("Synthetic hello", False)])
def test_documented_spam_adapter_imports_and_implements_interface(content, is_spam, load_adapter):
    checker = load_adapter("webmention.rst", "class MySpamChecker", "MySpamChecker")
    result = checker.check(Webmention(content=content))
    assert result == {
        "is_spam": is_spam,
        "confidence": 0.9 if is_spam else 0.1,
        "details": "Keyword-based detection",
    }
