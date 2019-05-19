from __future__ import unicode_literals, absolute_import

from django.conf.urls import url, include


urlpatterns = [
    # indieweb
    url(r"^indieweb/", include("indieweb.urls"))
]
