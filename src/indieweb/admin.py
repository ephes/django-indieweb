import json
from typing import Any

from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connections, router
from django.db.models import F, QuerySet
from django.forms import CharField, HiddenInput, ModelForm
from django.http import HttpRequest

from .models import (
    Auth,
    Profile,
    Token,
    Webmention,
    WebSubAcceptedDelivery,
    WebSubDeliveryAttempt,
    WebSubSubscription,
)


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


class WebSubSecretListFilter(admin.SimpleListFilter):
    """Filter subscriptions by whether they store a secret for signed deliveries."""

    title = "signed deliveries"
    parameter_name = "has_secret"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        return [("yes", "With secret"), ("no", "Without secret")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[WebSubSubscription]) -> QuerySet[WebSubSubscription]:
        if self.value() == "yes":
            return queryset.exclude(secret="")
        if self.value() == "no":
            return queryset.filter(secret="")
        return queryset


class WebSubSubscriptionAdminForm(ModelForm):
    """Keep the displayed editable values as a signed conflict baseline."""

    edit_baseline = CharField(widget=HiddenInput, required=False)
    editable_fields = (
        "hub_url",
        "topic_url",
        "state",
        "pending_mode",
        "requested_lease_seconds",
        "confirmed_lease_seconds",
        "lease_expires_at",
        "pending_secret_set",
    )
    transition_fields = (
        "state",
        "pending_mode",
        "confirmed_lease_seconds",
        "lease_expires_at",
        "pending_secret_set",
    )
    baseline_salt = "indieweb.subscription-admin"

    class Meta:
        model = WebSubSubscription
        fields = (
            "hub_url",
            "topic_url",
            "state",
            "pending_mode",
            "requested_lease_seconds",
            "confirmed_lease_seconds",
            "lease_expires_at",
            "pending_secret_set",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.baseline: dict[str, str] = {}
        if not self.instance.pk:
            return
        names = (*self.editable_fields, "request_generation")
        current = {name: self._baseline_value(name) for name in names}
        current["pk"] = str(self.instance.pk)
        self.initial["edit_baseline"] = signing.dumps(current, salt=self.baseline_salt)
        if not self.is_bound:
            return
        submitted_baseline = self.data.get(self.add_prefix("edit_baseline"), "")
        self.initial["edit_baseline"] = submitted_baseline
        try:
            baseline = signing.loads(submitted_baseline, salt=self.baseline_salt)
            if not isinstance(baseline, dict) or baseline.keys() != current.keys() or baseline["pk"] != current["pk"]:
                return
            self.baseline = baseline
            for name in self.editable_fields:
                field = self.instance._meta.get_field(name)
                self.initial[name] = (
                    field.to_python(baseline[name] or None) if field.null else field.to_python(baseline[name])
                )
        except signing.BadSignature:
            pass

    def _baseline_value(self, name: str) -> str:
        if getattr(self.instance, name) is None:
            return ""
        return str(self.instance._meta.get_field(name).value_to_string(self.instance))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if not self.instance.pk:
            return cleaned
        if not self.baseline:
            raise ValidationError("Subscription edit baseline is missing or invalid. Reload the page.")
        changed = set(self.changed_data).intersection(self.editable_fields)
        checked = changed.copy()
        if changed.intersection(self.transition_fields):
            checked.update((*self.transition_fields, "request_generation"))
        if any(self._baseline_value(name) != self.baseline[name] for name in checked):
            raise ValidationError("Subscription changed since this form was displayed. Reload the page.")
        # ModelForm would otherwise copy every posted (possibly stale) field
        # onto the locked current instance during _post_clean.
        for name in set(self.editable_fields) - changed:
            if name in cleaned:
                cleaned[name] = getattr(self.instance, name)
        return cleaned


@admin.register(WebSubSubscription)
class WebSubSubscriptionAdmin(admin.ModelAdmin):
    form = WebSubSubscriptionAdminForm

    def get_queryset(self, request: HttpRequest) -> QuerySet[WebSubSubscription]:
        queryset = super().get_queryset(request)
        if request.method == "POST":
            return queryset.using(router.db_for_write(WebSubSubscription))
        return queryset

    def get_object(self, request: HttpRequest, object_id: str, from_field: str | None = None) -> Any:
        # Django wraps change-form POSTs in an atomic block on this same write
        # database. Reserve SQLite's writer before the first subscription read.
        if request.method == "POST":
            field = self.model._meta.get_field(from_field) if from_field else self.model._meta.pk
            try:
                value = field.to_python(object_id)
            except (ValidationError, ValueError):
                return None
            queryset = self.get_queryset(request).filter(**{field.name: value})
            if connections[queryset.db].vendor == "sqlite":
                queryset.update(modified=F("modified"))
            return queryset.select_for_update().first()
        return super().get_object(request, object_id, from_field)

    def save_model(self, request: HttpRequest, obj: WebSubSubscription, form: Any, change: bool) -> None:
        if change:
            fields = set(form.changed_data).intersection(WebSubSubscriptionAdminForm.editable_fields)
            obj.save(using=router.db_for_write(WebSubSubscription), update_fields=fields | {"modified"})
        else:
            super().save_model(request, obj, form, change)

    list_display = (
        "topic_url",
        "hub_url",
        "state",
        "has_secret",
        "lease_expires_at",
        "last_denied_at",
        "last_delivery_at",
        "created",
    )
    list_filter = ("state", WebSubSecretListFilter, "created", "last_denied_at", "last_delivery_at")
    search_fields = ("topic_url", "hub_url")
    readonly_fields = (
        "masked_callback_token",
        "masked_secret",
        "masked_pending_secret",
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
        "last_accepted_delivery_at",
        "last_accepted_delivery_digest",
        "created",
        "modified",
    )
    ordering = ("-modified",)

    @admin.display(description="Callback token")
    def masked_callback_token(self, obj: WebSubSubscription) -> str:
        return obj.masked_callback_token()

    @admin.display(description="Signed deliveries", boolean=True)
    def has_secret(self, obj: WebSubSubscription) -> bool:
        """Whether the subscription stores a secret, so hub deliveries can be signature-checked."""
        return bool(obj.secret)

    @admin.display(description="Active secret")
    def masked_secret(self, obj: WebSubSubscription) -> str:
        return obj.masked_secret()

    @admin.display(description="Pending secret")
    def masked_pending_secret(self, obj: WebSubSubscription) -> str:
        return obj.masked_pending_secret()

    fieldsets = (
        (
            "Subscription",
            {"fields": ("hub_url", "topic_url", "masked_callback_token", "state", "pending_mode", "edit_baseline")},
        ),
        (
            "Lease",
            {"fields": ("requested_lease_seconds", "confirmed_lease_seconds", "lease_expires_at")},
        ),
        ("Secret", {"fields": ("masked_secret", "masked_pending_secret", "pending_secret_set")}),
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
                    "last_accepted_delivery_at",
                    "last_accepted_delivery_digest",
                ),
            },
        ),
        ("Timestamps", {"fields": ("created", "modified")}),
    )


@admin.register(WebSubAcceptedDelivery)
class WebSubAcceptedDeliveryAdmin(admin.ModelAdmin):
    list_display = ("subscription", "accepted_at", "body_digest")
    list_filter = ("accepted_at",)
    search_fields = ("subscription__topic_url", "subscription__hub_url", "body_digest")
    readonly_fields = ("subscription", "body_digest", "accepted_at", "created", "modified")
    ordering = ("-accepted_at", "-pk")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


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

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ("client_id", "owner", "scope", "created")
    list_filter = ("owner", "created")
    search_fields = ("client_id", "me")
    readonly_fields = ("masked_key", "owner", "client_id", "me", "scope", "created", "modified")
    ordering = ("-created",)

    @admin.display(description="Token")
    def masked_key(self, obj: Token) -> str:
        return obj.masked_key()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    fieldsets = (
        (
            "Token Information",
            {
                "fields": ("masked_key", "client_id", "me", "scope"),
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
    search_fields = ("client_id", "me")
    ordering = ("-created",)

    @admin.display(description="Authorization code")
    def masked_key(self, obj: Auth) -> str:
        return obj.masked_key()

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        fields = [f.name for f in self.model._meta.fields if f.name != "key"]
        fields.append("masked_key")
        return fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    fieldsets = (
        (
            "Authorization Details",
            {
                "fields": ("masked_key", "state", "client_id", "redirect_uri", "scope", "me"),
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

    h_card = CharField(widget=PrettyJSONWidget, required=False, strip=False)

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

        # Bound decoding work/allocation before parsing; the h-card validator
        # separately bounds the decoded tree to 32 levels and 10,000 nodes.
        try:
            if len(h_card_str) > 262_144 or len(h_card_str.encode("utf-8")) > 262_144:
                raise ValueError("JSON byte budget exceeded")
            if not h_card_str or not h_card_str.strip():
                return {}
            h_card = json.loads(h_card_str)
        except (ValueError, RecursionError, OverflowError) as exc:
            raise ValidationError("Invalid JSON: malformed data or resource limit exceeded.") from exc

        # Import validation from h_card module
        from .h_card import validate_h_card

        if not validate_h_card(h_card):
            raise ValidationError("Invalid h-card structure. Properties must be lists with unambiguous names.")

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
