from django.urls import path

from .views import application_create, application_received

urlpatterns = [
    path("apply/", application_create, name="logistics_application_create"),
    path("apply/received/", application_received, name="logistics_application_received"),
]
