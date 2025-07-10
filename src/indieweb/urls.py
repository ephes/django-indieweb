"""
IndieWeb endpoint URLs.

Add these to your root URLconf if you're using the indieweb endpoints::

    urlpatterns = [
        ...
        path('indieweb/', include('indieweb.urls')),
    ]

The namespace 'indieweb' is automatically set via app_name.
"""

from django.urls import path

from . import views

app_name = "indieweb"
urlpatterns = [
    path("auth/", views.AuthView.as_view(), name="auth"),
    path("token/", views.TokenView.as_view(), name="token"),
    path("micropub/", views.MicropubView.as_view(), name="micropub"),
    path("webmention/", views.WebmentionEndpoint.as_view(), name="webmention"),
]
