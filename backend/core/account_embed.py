"""Permit same-origin embedding of account-management pages inside Settings.

Django's default DENY is retained for all other paths, and the browser must
still be on the same origin. Authentication, OIDC callbacks and admin pages
retain their original access controls.
"""


class AccountEmbedFrameMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if request.user.is_authenticated and (
            path.startswith("/accounts/")
            or path.startswith("/accounts/security/oidc/")
        ):
            response["X-Frame-Options"] = "SAMEORIGIN"
        return response
