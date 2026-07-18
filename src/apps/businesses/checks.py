from __future__ import annotations

from django.core.checks import Error, Tags, register

from .stripe_config import validate_stripe_configuration


@register(Tags.security)
def check_stripe_configuration(app_configs, **kwargs):
    return [
        Error(
            issue.message,
            id=issue.id,
        )
        for issue in validate_stripe_configuration()
    ]
