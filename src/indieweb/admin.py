import json
from typing import Any

from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.core.exceptions import ValidationError
from django.forms import CharField, ModelForm
from django.http import HttpRequest

from .models import Auth, Profile, Token, Webmention, WebSubDeliveryAttempt, WebSubSubscription


@admin.register(Webmention)
class WebmentionAdmin(admin.ModelAdmin):
    list_display = ("source_url", "target_url", "status", "mention_type", "author_name", "vouch_url", "created")
    list_filter = ("status", "mention_type", "created")
    search_fields = ("source_url", "target_url", "vouch_url", "author_name")
    readonly_fields = ("verified_at", "vouch_verified_at", "spam_check_result", "created", "modified")
    ordering = ("-created",)
    date_hierarchy = "created"

    fieldsets = (
        (
            "URLs",
            {
                "fields": ("source_url", "target_url", "vouch_url"),
            },
        ),
        (
            "Status",
            {
                "fields": ("status", "mention_type", "verified_at", "vouch_verified_at"),
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


@admin.register(WebSubSubscription)
class WebSubSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "topic_url",
        "hub_url",
        "state",
        "lease_expires_at",
        "last_denied_at",
        "last_delivery_at",
        "created",
    )
    list_filter = ("state", "created", "last_denied_at", "last_delivery_at")
    search_fields = ("topic_url", "hub_url")
    readonly_fields = (
        "callback_token",
        "last_challenge",
        "last_verified_at",
        "last_request_at",
        "last_request_mode",
        "last_request_status_code",
        "last_request_error",
        "last_denied_at",
        "last_denied_mode",
        "last_denial_reason",
        "last_delivery_at",
        "last_delivery_content_type",
        "last_delivery_size",
        "last_delivery_digest",
        "last_delivery_signature_algorithm",
        "last_delivery_status_code",
        "last_delivery_error",
        "created",
        "modified",
    )
    ordering = ("-modified",)

    fieldsets = (
        ("Subscription", {"fields": ("hub_url", "topic_url", "callback_token", "state", "pending_mode")}),
        (
            "Lease",
            {"fields": ("requested_lease_seconds", "confirmed_lease_seconds", "lease_expires_at")},
        ),
        ("Secret", {"fields": ("secret", "pending_secret", "pending_secret_set")}),
        (
            "Latest Request",
            {
                "fields": (
                    "last_request_at",
                    "last_request_mode",
                    "last_request_status_code",
                    "last_request_error",
                    "last_denied_at",
                    "last_denied_mode",
                    "last_denial_reason",
                    "last_challenge",
                    "last_verified_at",
                ),
            },
        ),
        (
            "Latest Delivery",
            {
                "fields": (
                    "last_delivery_at",
                    "last_delivery_content_type",
                    "last_delivery_size",
                    "last_delivery_digest",
                    "last_delivery_signature_algorithm",
                    "last_delivery_status_code",
                    "last_delivery_error",
                ),
            },
        ),
        ("Timestamps", {"fields": ("created", "modified")}),
    )


@admin.register(WebSubDeliveryAttempt)
class WebSubDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ("subscription", "received_at", "status_code", "content_type", "size", "signature_algorithm")
    list_filter = ("status_code", "received_at", "signature_algorithm")
    search_fields = ("subscription__topic_url", "subscription__hub_url", "digest", "error")
    readonly_fields = (
        "subscription",
        "received_at",
        "content_type",
        "size",
        "digest",
        "signature_algorithm",
        "status_code",
        "error",
        "created",
        "modified",
    )
    ordering = ("-received_at", "-pk")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


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
