'''
Indiweb endpoint urls.

Add these to your root URLconf if you're using the indieweb endpoints:

    urlpatterns = [
        ...
        url(r'^indieweb/', include('indieweb.urls', namespace='indieweb'))
    ]

In Django versions older than 1.9, the urls must be namespaced as 'indieweb'.
'''
from __future__ import unicode_literals

from django.conf.urls import url

from . import views


app_name = 'indieweb'
urlpatterns = [
    url(r'^auth/$', views.AuthView.as_view(), name="auth"),
    url(r'^token/$', views.TokenView.as_view(), name="token"),
#    url(r'^micropub/$', views.MicropubView.as_view(), name="micropub"),
]
