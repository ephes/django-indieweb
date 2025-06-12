from django.urls import include, path

urlpatterns = [
    # indieweb
    path("indieweb/", include("indieweb.urls"))
]
