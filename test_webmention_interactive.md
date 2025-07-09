# Testing Webmention Features

## 1. Set Up Test Environment

First, ensure you have the development server running:

```bash
# In one terminal:
uv run python manage.py migrate
uv run python manage.py runserver
```

## 2. Test Webmention Endpoint Discovery

Your site now exposes a webmention endpoint at `/webmention/`. You can verify this:

```bash
# Check the endpoint is accessible
curl -I http://localhost:8000/webmention/
```

The response should include a Link header advertising the endpoint:
```
Link: <http://localhost:8000/webmention/>; rel="webmention"
```

## 3. Test Receiving Webmentions

Send a test webmention to your endpoint:

```bash
# Basic webmention
curl -X POST http://localhost:8000/webmention/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "source=https://alice.example/post-about-you" \
  -d "target=http://localhost:8000/my-post/"

# Should return 202 Accepted if successful
```

## 4. Test Sending Webmentions

Use the management command to send webmentions:

```bash
# Dry run to see what would be sent
uv run python manage.py send_webmentions https://mysite.com/my-new-post/ --dry-run

# Actually send webmentions
uv run python manage.py send_webmentions https://mysite.com/my-new-post/

# Send with custom HTML content
echo '<a href="https://example.com/their-post">Great article!</a>' | \
  uv run python manage.py send_webmentions https://mysite.com/my-post/ --stdin
```

## 5. Test with webmention.rocks

[Webmention.rocks](https://webmention.rocks/) provides a test suite for webmention implementations:

1. **Receiver Tests**: Point webmention.rocks tests at your endpoint
   - Go to https://webmention.rocks/receive/1
   - Enter your webmention endpoint: `http://localhost:8000/webmention/`
   - Run the tests

2. **Sender Tests**: Test discovery and sending
   - Each test provides a URL to check for webmention endpoints
   - Use the management command to test sending

## 6. Test in Django Shell

```bash
uv run python manage.py shell
```

```python
# Test the sender
from indieweb.senders import WebmentionSender

sender = WebmentionSender()

# Test endpoint discovery
endpoint = sender.discover_endpoint("https://webmention.rocks/test/1")
print(f"Found endpoint: {endpoint}")

# Test the processor
from indieweb.processors import WebmentionProcessor
from indieweb.models import Webmention

processor = WebmentionProcessor()

# Create and process a test webmention
wm = processor.process_webmention(
    "https://example.com/post",
    "http://localhost:8000/my-post/"
)
print(f"Webmention status: {wm.status}")

# View all webmentions
for w in Webmention.objects.all():
    print(f"{w.source_url} -> {w.target_url}: {w.status}")
```

## 7. Test Template Integration

Create a test view or template:

```html
<!-- In a template -->
{% load webmentions %}

<!-- Show webmention endpoint link in head -->
{% webmention_endpoint_link %}

<!-- Display webmentions for a URL -->
<div class="webmentions">
    <h3>Responses ({% webmention_count "http://localhost:8000/my-post/" %})</h3>
    {% webmentions_for "http://localhost:8000/my-post/" %}
</div>
```

## 8. Test with Real Sites

Some sites that support webmentions:
- https://indieweb.org/
- https://aaronparecki.com/
- https://adactio.com/

Try mentioning their posts and see if they send webmentions back!

## 9. Check Django Admin

If you have Django admin enabled:
1. Go to http://localhost:8000/admin/
2. Look for the Webmention model
3. You can view and manage all received webmentions there

## Debugging Tips

1. **Check logs** when receiving webmentions:
   ```python
   # The processor logs at INFO level
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

2. **Inspect webmention data**:
   ```python
   from indieweb.models import Webmention
   
   # See all fields
   wm = Webmention.objects.latest('created')
   print(f"Author: {wm.author_name}")
   print(f"Content: {wm.content}")
   print(f"Type: {wm.mention_type}")
   ```

3. **Test spam checking** (if configured):
   ```python
   from django.conf import settings
   print(settings.INDIEWEB_SPAM_CHECKER)  # Should show the configured class
   ```