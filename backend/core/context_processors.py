from django.conf import settings
from core.first_run import needs_setup


def account_capabilities(_request):
    """Expose non-secret account onboarding capabilities to allauth templates."""
    return {
        "makervault_local_registration": bool(settings.ALLOW_LOCAL_REGISTRATION),
        "makervault_email_enabled": bool(getattr(settings, "EMAIL_HOST", "")),
        "makervault_initial_setup_available": needs_setup() if _request is not None else False,
    }
