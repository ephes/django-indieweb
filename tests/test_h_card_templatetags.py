import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template

from indieweb.models import Profile

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="testuser", email="test@example.com")


@pytest.fixture
def profile(user):
    return Profile.objects.create(
        user=user,
        name="Test User",
        photo_url="https://example.com/photo.jpg",
        url="https://example.com",
        h_card={
            "name": ["Test User"],
            "photo": ["https://example.com/photo.jpg"],
            "url": ["https://example.com", "https://social.example/@testuser"],
            "email": ["test@example.com"],
            "note": ["Software developer"],
            "nickname": ["testuser"],
        },
    )


def test_h_card_tag_with_user(user, profile):
    """Test h_card tag renders correctly with user object."""
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    context = Context({"user": user})
    rendered = template.render(context)

    assert "h-card" in rendered
    assert "Test User" in rendered
    assert "https://example.com/photo.jpg" in rendered
    assert "p-name" in rendered
    assert "u-photo" in rendered


def test_h_card_tag_with_profile(profile):
    """Test h_card tag renders correctly with profile object."""
    template = Template("{% load indieweb_tags %}{% h_card profile %}")
    context = Context({"profile": profile})
    rendered = template.render(context)

    assert "h-card" in rendered
    assert "Test User" in rendered


def test_h_card_tag_handles_missing_profile():
    """Test h_card tag handles users without profiles gracefully."""
    user_without_profile = User.objects.create_user(username="nocard")
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    context = Context({"user": user_without_profile})
    rendered = template.render(context)

    assert "h-card" in rendered
    assert "nocard" in rendered  # Should show username as fallback


def test_h_card_renders_multiple_urls(user, profile):
    """Test that multiple URLs are rendered correctly."""
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    context = Context({"user": user})
    rendered = template.render(context)

    assert "https://example.com" in rendered
    assert "https://social.example/@testuser" in rendered


def test_h_card_renders_address(user, profile):
    """Test address rendering in h-card."""
    profile.h_card["adr"] = [{"locality": "Portland", "region": "OR", "country_name": "USA"}]
    profile.save()

    template = Template("{% load indieweb_tags %}{% h_card user %}")
    context = Context({"user": user})
    rendered = template.render(context)

    assert "p-adr" in rendered
    assert "p-locality" in rendered
    assert "Portland" in rendered


def test_h_card_org_url_uses_outbound_link_attributes(user, profile):
    """Organization URLs include the same outbound link hardening as Webmentions."""
    profile.h_card["org"] = [{"name": "Example Org", "url": "https://org.example"}]
    profile.save()

    template = Template("{% load indieweb_tags %}{% h_card user %}")
    context = Context({"user": user})
    rendered = template.render(context)

    assert "Example Org" in rendered
    assert 'href="https://org.example"' in rendered
    assert 'rel="nofollow noopener ugc"' in rendered
    assert 'referrerpolicy="no-referrer"' in rendered


def test_h_card_first_url_keeps_rel_me_with_noopener(user, profile):
    """The first profile URL keeps ``rel="me"`` for IndieAuth and adds noopener."""
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    rendered = template.render(Context({"user": user}))
    assert 'rel="me noopener"' in rendered
    assert 'referrerpolicy="no-referrer"' in rendered


def test_h_card_subsequent_urls_use_nofollow_noopener(user, profile):
    """Additional profile URLs are marked ``rel="nofollow noopener"``."""
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    rendered = template.render(Context({"user": user}))
    assert 'rel="nofollow noopener"' in rendered
    assert "https://social.example/@testuser" in rendered


def test_h_card_photo_includes_referrer_policy(user, profile):
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    rendered = template.render(Context({"user": user}))
    assert 'src="https://example.com/photo.jpg"' in rendered
    assert 'referrerpolicy="no-referrer"' in rendered


def test_h_card_first_safe_url_keeps_rel_me_when_earlier_url_was_unsafe(user, profile):
    """``rel="me"`` must apply to the first *emitted* safe URL, not the first raw entry.

    A bypass-injected unsafe URL at position 0 must not strip IndieAuth
    identity-discovery semantics from the only valid profile link rendered.
    """
    Profile.objects.filter(pk=profile.pk).update(
        h_card={
            "name": ["Test User"],
            "url": ["javascript:alert(1)", "https://safe.example/"],
        }
    )
    fresh_profile = Profile.objects.get(pk=profile.pk)
    template = Template("{% load indieweb_tags %}{% h_card profile %}")
    rendered = template.render(Context({"profile": fresh_profile}))
    assert "javascript:" not in rendered
    assert 'href="https://safe.example/" rel="me noopener"' in rendered
    assert 'rel="nofollow noopener"' not in rendered


def test_h_card_render_drops_unsafe_url_from_bypassed_h_card(user, profile):
    """Bypass paths (QuerySet.update) skip full_clean; render must still drop bad URLs."""
    Profile.objects.filter(pk=profile.pk).update(
        h_card={
            "name": ["Test User"],
            "url": ["javascript:alert(1)", "https://safe.example/"],
            "photo": ["data:image/svg+xml,<svg onload=alert(1)>"],
        }
    )
    fresh_profile = Profile.objects.get(pk=profile.pk)
    template = Template("{% load indieweb_tags %}{% h_card profile %}")
    rendered = template.render(Context({"profile": fresh_profile}))
    assert "javascript:" not in rendered
    assert "data:image/svg+xml" not in rendered
    assert "https://safe.example/" in rendered


def test_h_card_render_drops_unsafe_quick_access_fields(user, profile):
    """``Profile.url``/``photo_url`` injected via QuerySet.update must not render."""
    Profile.objects.filter(pk=profile.pk).update(
        h_card={},
        url="javascript:alert(1)",
        photo_url="data:image/png;base64,AAAA",
    )
    fresh_profile = Profile.objects.get(pk=profile.pk)
    template = Template("{% load indieweb_tags %}{% h_card profile %}")
    rendered = template.render(Context({"profile": fresh_profile}))
    assert "javascript:" not in rendered
    assert "data:image/png" not in rendered
    assert 'class="u-url"' not in rendered
    assert 'class="u-photo"' not in rendered


def test_h_card_render_drops_unsafe_org_url_from_bypassed_h_card(user, profile):
    Profile.objects.filter(pk=profile.pk).update(
        h_card={"org": [{"name": "Bad Org", "url": "javascript:alert(1)"}]},
        url="",
    )
    fresh_profile = Profile.objects.get(pk=profile.pk)
    template = Template("{% load indieweb_tags %}{% h_card profile %}")
    rendered = template.render(Context({"profile": fresh_profile}))
    assert "Bad Org" in rendered
    assert "javascript:" not in rendered
    assert 'class="u-url"' not in rendered
