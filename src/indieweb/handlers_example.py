"""
Example Micropub content handlers for common use cases.

These examples show how to integrate Micropub with different Django models.
Copy and adapt these for your own application.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.db import models

from .handlers import MicropubContentHandler, MicropubEntry

User = get_user_model()


# Example 1: Simple Blog Post Model
class SimpleBlogPost(models.Model):
    """Example blog post model for demonstration."""

    author = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField()
    slug = models.SlugField(unique=True)
    published = models.DateTimeField(auto_now_add=True)
    tags = models.JSONField(default=list)  # Store tags as JSON array

    def __str__(self) -> str:
        return self.title or f"Post {self.slug}"

    def get_absolute_url(self):
        return f"/blog/{self.slug}/"


class SimpleBlogHandler(MicropubContentHandler):
    """
    Example handler for a simple blog.

    This demonstrates the minimal implementation needed to create posts
    from Micropub requests.
    """

    def create_entry(self, properties: dict[str, list[Any]], user: User) -> MicropubEntry:
        import uuid

        from django.utils.text import slugify

        # Extract content
        content = properties.get("content", [""])[0]
        name = properties.get("name", [""])[0]
        categories = properties.get("category", [])

        # Generate slug
        if name:
            base_slug = slugify(name)[:50]
        else:
            # For notes without titles, use first few words
            base_slug = slugify(content[:50])

        # Ensure unique slug
        slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        # Create post
        post = SimpleBlogPost.objects.create(author=user, title=name, content=content, slug=slug, tags=categories)

        return MicropubEntry(url=post.get_absolute_url(), properties=properties)

    def get_entry(self, url: str, user: User) -> MicropubEntry | None:
        try:
            # Extract slug from URL
            slug = url.strip("/").split("/")[-1]
            post = SimpleBlogPost.objects.get(slug=slug, author=user)

            properties = {
                "content": [post.content],
                "published": [post.published.isoformat()],
                "category": post.tags,
            }
            if post.title:
                properties["name"] = [post.title]

            return MicropubEntry(url=post.get_absolute_url(), properties=properties)
        except SimpleBlogPost.DoesNotExist:
            return None

    def _apply_replace_updates(self, post: SimpleBlogPost, updates: dict[str, list]) -> None:
        """Apply replace operations to a post."""
        for key, values in updates.items():
            if key == "content":
                post.content = values[0]
            elif key == "name":
                post.title = values[0]
            elif key == "category":
                post.tags = values

    def _apply_add_updates(self, post: SimpleBlogPost, updates: dict[str, list]) -> None:
        """Apply add operations to a post."""
        for key, values in updates.items():
            if key == "category":
                # Add new tags without duplicates
                post.tags = list(set(post.tags + values))

    def _apply_delete_updates(self, post: SimpleBlogPost, deletes: Any) -> None:
        """Apply delete operations to a post."""
        if isinstance(deletes, list):
            # Delete entire properties
            for key in deletes:
                if key == "name":
                    post.title = ""
                elif key == "category":
                    post.tags = []

    def update_entry(self, url: str, updates: dict[str, Any], user: User) -> MicropubEntry:
        slug = url.strip("/").split("/")[-1]
        post = SimpleBlogPost.objects.get(slug=slug, author=user)

        if "replace" in updates:
            self._apply_replace_updates(post, updates["replace"])

        if "add" in updates:
            self._apply_add_updates(post, updates["add"])

        if "delete" in updates:
            self._apply_delete_updates(post, updates["delete"])

        post.save()
        return self.get_entry(url, user)

    def delete_entry(self, url: str, user: User) -> None:
        slug = url.strip("/").split("/")[-1]
        SimpleBlogPost.objects.filter(slug=slug, author=user).delete()

    def undelete_entry(self, url: str, user: User) -> MicropubEntry:
        # This simple example doesn't support undelete
        # You could implement soft deletes if needed
        raise ValueError("Undelete not supported")


# Example 2: Multi-user site with draft support
class DraftAwareBlogHandler(SimpleBlogHandler):
    """
    Extended handler that supports draft posts and multiple users.
    """

    def create_entry(self, properties: dict[str, list[Any]], user: User) -> MicropubEntry:
        # Check for draft status
        post_status = properties.get("post-status", ["published"])[0]

        # Create entry using parent method
        entry = super().create_entry(properties, user)

        # If draft, update the post
        if post_status == "draft":
            slug = entry.url.strip("/").split("/")[-1]
            _post = SimpleBlogPost.objects.get(slug=slug)
            # You'd add a status field to your model
            # post.status = 'draft'
            # post.save()

        return entry

    def get_config(self, user: User) -> dict[str, Any]:
        config = super().get_config(user)

        # Add draft support
        config["post-status"] = ["published", "draft"]

        # Add supported vocabulary
        config["post-types"] = [
            {"type": "note", "name": "Note", "properties": ["content"]},
            {"type": "article", "name": "Article", "properties": ["name", "content"]},
            {"type": "photo", "name": "Photo", "properties": ["photo", "content"]},
            {"type": "reply", "name": "Reply", "properties": ["in-reply-to", "content"]},
        ]

        return config


# Example 3: Integration with existing blog system
class ExistingBlogIntegrationHandler(MicropubContentHandler):
    """
    Example showing how to integrate with an existing blog system
    that has its own models and URL structure.
    """

    def create_entry(self, properties: dict[str, list[Any]], user: User) -> MicropubEntry:
        # Import your existing models
        # from myapp.models import BlogPost, Category

        # Map Micropub properties to your model fields
        _content = properties.get("content", [""])[0]
        title = properties.get("name", [""])[0]

        # Determine post type based on properties
        _post_type = "note"
        if properties.get("in-reply-to"):
            _post_type = "reply"
        elif properties.get("bookmark-of"):
            _post_type = "bookmark"
        elif properties.get("like-of"):
            _post_type = "like"
        elif title:
            _post_type = "article"

        # Create post using your existing system
        # post = BlogPost.objects.create(
        #     author=user,
        #     title=title or f"Note from {datetime.now()}",
        #     content=content,
        #     post_type=post_type,
        #     metadata=properties  # Store original for reference
        # )

        # Handle categories using your existing system
        # for tag_name in properties.get('category', []):
        #     tag = Category.objects.get_or_create(name=tag_name)[0]
        #     post.categories.add(tag)

        # Return the URL from your existing URL structure
        # return MicropubEntry(
        #     url=post.get_absolute_url(),
        #     properties=properties
        # )

        # Placeholder for example
        return MicropubEntry(url="/placeholder/", properties=properties)

    def get_entry(self, url: str, user: User) -> MicropubEntry | None:
        # Implement based on your URL structure
        return None

    def update_entry(self, url: str, updates: dict[str, Any], user: User) -> MicropubEntry:
        # Implement based on your model structure
        raise NotImplementedError("Update not yet implemented")

    def delete_entry(self, url: str, user: User) -> None:
        # Implement based on your deletion strategy
        raise NotImplementedError("Delete not yet implemented")

    def undelete_entry(self, url: str, user: User) -> MicropubEntry:
        # Only if you support soft deletes
        raise NotImplementedError("Undelete not supported")


# Usage in settings.py:
# INDIEWEB_MICROPUB_HANDLER = 'indieweb.handlers_example.SimpleBlogHandler'
