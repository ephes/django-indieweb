import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import isolate_apps
from django.urls import reverse

from indieweb.models import Token


@pytest.fixture
def example_posts(transactional_db, settings):
    # Treat the copyable example module as a project app only for model setup.
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "examples"]), isolate_apps("examples"):
        from examples.handlers_example import SimpleBlogPost

    with connection.schema_editor() as editor:
        editor.create_model(SimpleBlogPost)
    try:
        yield SimpleBlogPost
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(SimpleBlogPost)


@pytest.mark.parametrize("handler", ["SimpleBlogHandler", "DraftAwareBlogHandler"])
def test_blog_example_refuses_draft_creates(client, settings, example_posts, handler):
    settings.INDIEWEB_MICROPUB_HANDLER = f"examples.handlers_example.{handler}"
    user = get_user_model().objects.create_user(username="example-writer")
    token = Token.objects.create(
        me="https://writer.example.org/", client_id="https://client.example.org/", scope="create", owner=user
    )
    headers = {"Authorization": f"Bearer {token.key}"}
    url = reverse("indieweb:micropub")
    post = {"h": "entry", "content": "Synthetic draft post"}

    response = client.post(url, {**post, "post-status": "draft"}, headers=headers)
    assert response.status_code == 400
    assert response.content == b"invalid_request"
    assert "Location" not in response
    assert not example_posts.objects.exists()

    config = client.get(url, {"q": "config"}, headers=headers)
    assert config.status_code == 200
    assert "post-status" not in config.json()

    published = client.post(
        url, {**post, "content": "Synthetic public post", "post-status": "published"}, headers=headers
    )
    assert published.status_code == 201
    assert example_posts.objects.get().content == "Synthetic public post"
