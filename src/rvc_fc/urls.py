from django.urls import path

from rvc_fc.views import home

urlpatterns = [
    path("", home)
]
