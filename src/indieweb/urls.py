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
    path("auth/metadata/", views.IndieAuthMetadataView.as_view(), name="auth-metadata"),
    path("token/", views.TokenView.as_view(), name="token"),
    path("tokens/", views.TokenManagementView.as_view(), name="tokens"),
    path("tokens/<int:pk>/revoke/", views.TokenRevokeView.as_view(), name="token-revoke"),
    path("micropub/", views.MicropubView.as_view(), name="micropub"),
    path("media/", views.MicropubMediaView.as_view(), name="media"),
    path("websub/<str:token>/", views.WebSubCallbackView.as_view(), name="websub-callback"),
    path("webmention/", views.WebmentionEndpoint.as_view(), name="webmention"),
    path("webmention/<int:pk>/", views.WebmentionStatusView.as_view(), name="webmention-status"),
]
