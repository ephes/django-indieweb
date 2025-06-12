"""
Indiweb endpoint urls.

Add these to your root URLconf if you're using the indieweb endpoints:

    urlpatterns = [
        ...
        url(r'^indieweb/', include('indieweb.urls', namespace='indieweb'))
    ]

In Django versions older than 1.9, the urls must be namespaced as 'indieweb'.
"""

from django.urls import path

from . import views

app_name = "indieweb"
urlpatterns = [
    path("auth/", views.AuthView.as_view(), name="auth"),
    path("token/", views.TokenView.as_view(), name="token"),
    path("micropub/", views.MicropubView.as_view(), name="micropub"),
]
