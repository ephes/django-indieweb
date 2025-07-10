from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Auth, Token, Webmention


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
