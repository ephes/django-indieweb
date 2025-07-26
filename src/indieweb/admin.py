import json
from typing import Any

from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.core.exceptions import ValidationError
from django.forms import CharField, ModelForm
from django.http import HttpRequest

from .models import Auth, Profile, Token, Webmention


@admin.register(Webmention)
class WebmentionAdmin(admin.ModelAdmin):
    list_display = ("source_url", "target_url", "status", "mention_type", "author_name", "created")
    list_filter = ("status", "mention_type", "created")
    search_fields = ("source_url", "target_url", "author_name")
    readonly_fields = ("verified_at", "spam_check_result", "created", "modified")
    ordering = ("-created",)
    date_hierarchy = "created"

    fieldsets = (
        (
            "URLs",
            {
                "fields": ("source_url", "target_url"),
            },
        ),
        (
            "Status",
            {
                "fields": ("status", "mention_type", "verified_at"),
            },
        ),
        (
            "Author Information",
            {
                "fields": ("author_name", "author_url", "author_photo"),
            },
        ),
        (
            "Content",
            {
                "fields": ("content", "content_html", "published"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("spam_check_result", "created", "modified"),
            },
        ),
    )


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ("client_id", "owner", "scope", "created")
    list_filter = ("owner", "created")
    search_fields = ("client_id", "me")
    readonly_fields = ("key", "owner", "client_id", "me", "scope", "created", "modified")
    ordering = ("-created",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    fieldsets = (
        (
            "Token Information",
            {
                "fields": ("key", "client_id", "me", "scope"),
            },
        ),
        (
            "Ownership",
            {
                "fields": ("owner",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created", "modified"),
            },
        ),
    )


@admin.register(Auth)
class AuthAdmin(admin.ModelAdmin):
    list_display = ("client_id", "owner", "state", "created")
    list_filter = ("owner", "created")
    search_fields = ("client_id", "me", "state")
    ordering = ("-created",)

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    fieldsets = (
        (
            "Authorization Details",
            {
                "fields": ("key", "state", "client_id", "redirect_uri", "scope", "me"),
            },
        ),
        (
            "Ownership",
            {
                "fields": ("owner",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created", "modified"),
            },
        ),
    )


class PrettyJSONWidget(AdminTextareaWidget):
    """Widget to display JSON in a pretty format with larger textarea."""

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        default_attrs = {"rows": 20, "cols": 80, "style": "font-family: monospace;"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)


class ProfileAdminForm(ModelForm):
    """Custom form for Profile admin with pretty JSON editing."""

    h_card = CharField(widget=PrettyJSONWidget, required=False)

    class Meta:
        model = Profile
        fields = ["user", "h_card", "name", "photo_url", "url"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Convert the h_card dict to JSON string for display
        if self.instance and self.instance.h_card:
            self.initial["h_card"] = json.dumps(self.instance.h_card, indent=2, sort_keys=True, ensure_ascii=False)

    def clean_h_card(self) -> dict[str, Any]:
        """Validate and parse h_card JSON structure."""
        h_card_str = self.cleaned_data.get("h_card", "")

        if not h_card_str or h_card_str.strip() == "":
            return {}

        try:
            h_card = json.loads(h_card_str)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}") from e

        # Import validation from h_card module
        from .h_card import validate_h_card

        if not validate_h_card(h_card):
            raise ValidationError("Invalid h-card structure. All properties must be lists.")

        # Ensure we return a dict
        return dict(h_card) if h_card else {}


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    form = ProfileAdminForm
    list_display = ("user", "name", "url", "created", "modified")
    list_filter = ("created", "modified")
    search_fields = ("user__username", "user__email", "name", "url")
    readonly_fields = ("created", "modified")
    ordering = ("-modified",)

    fieldsets = (
        (
            "User",
            {
                "fields": ("user",),
            },
        ),
        (
            "Quick Access Fields",
            {
                "fields": ("name", "photo_url", "url"),
                "description": "Common fields for easy access and querying",
            },
        ),
        (
            "H-Card Data",
            {
                "fields": ("h_card",),
                "description": "Full h-card data in JSON format (see https://microformats.org/wiki/h-card)",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created", "modified"),
            },
        ),
    )
