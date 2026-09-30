from django.test import SimpleTestCase


class OidcDependencySmokeTests(SimpleTestCase):
    def test_openid_connect_provider_imports_without_oauthlib(self):
        import jwt
        from allauth.socialaccount.providers.openid_connect.provider import (
            OpenIDConnectProvider,
        )

        self.assertTrue(jwt.__version__)
        self.assertEqual(OpenIDConnectProvider.id, "openid_connect")
