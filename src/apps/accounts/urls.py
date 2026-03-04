from django.contrib import admin
from django.urls import path, include
from .views import agent_login

urlpatterns = [
    path('agent_login', agent_login, name='agent_login'),

]