from django.urls import path

from .views import (
    agent_login,
    customer_registration,
    saas_profile,
)

urlpatterns = [
    path('agent_login', agent_login, name='agent_login'),
    path('customer_registration', customer_registration, name='customer_registration'),
    path('profile', saas_profile, name='saas_profile'),
]
