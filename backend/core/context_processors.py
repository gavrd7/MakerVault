from django.conf import settings


def account_capabilities(_request):
    """Expose non-secret account onboarding capabilities to allauth templates."""
    return {
        "makervault_local_registration": bool(settings.ALLOW_LOCAL_REGISTRATION),
        "makervault_email_enabled": bool(getattr(settings, "EMAIL_HOST", "")),
    }
