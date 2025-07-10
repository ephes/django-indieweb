from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # admin
    path("admin/", admin.site.urls),
    # indieweb
    path("indieweb/", include("indieweb.urls")),
]
