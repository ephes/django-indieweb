#!/usr/bin/env python
"""Test webmention functionality locally."""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

from indieweb.models import Webmention
from indieweb.processors import WebmentionProcessor
from indieweb.senders import WebmentionSender


def test_receiving():
    """Test receiving a webmention."""
    print("Testing Webmention Receiving...")
    
    processor = WebmentionProcessor()
    
    # Create a test webmention
    source = "https://example.com/mentioning-post"
    target = "https://mysite.com/mentioned-post"
    
    # This would normally fetch the source, but for testing we'll create directly
    webmention = Webmention.objects.create(
        source_url=source,
        target_url=target,
        status="pending"
    )
    
    print(f"Created webmention: {webmention}")
    print(f"Status: {webmention.status}")
    
    # List all webmentions
    print("\nAll webmentions:")
    for wm in Webmention.objects.all():
        print(f"  - {wm}")


def test_sending():
    """Test sending webmentions."""
    print("\nTesting Webmention Sending...")
    
    sender = WebmentionSender()
    
    # Test HTML with some links
    html_content = """
    <html>
    <body>
        <p>I just read this great article: 
           <a href="https://example.com/great-article">Great Article</a>
        </p>
        <p>Also check out <a href="https://another-site.com/post">this post</a></p>
    </body>
    </html>
    """
    
    # Extract URLs
    urls = sender.extract_urls(html_content)
    print(f"Found {len(urls)} URLs: {urls}")
    
    # Test endpoint discovery (this would make real HTTP requests)
    for url in urls:
        print(f"\nChecking {url} for webmention endpoint...")
        # endpoint = sender.discover_endpoint(url)
        # print(f"  Endpoint: {endpoint}")


def test_in_template():
    """Show how to use in templates."""
    print("\nTemplate Usage Examples:")
    print("""
    1. Show webmentions for a URL:
       {% load webmentions %}
       {% webmentions_for "https://mysite.com/post/" %}
    
    2. Count webmentions:
       {% webmention_count "https://mysite.com/post/" %}
    
    3. Add endpoint discovery link:
       {% webmention_endpoint_link %}
    """)


if __name__ == "__main__":
    print("Django IndieWeb - Webmention Testing\n")
    
    test_receiving()
    test_sending()
    test_in_template()
    
    print("\nDone!")