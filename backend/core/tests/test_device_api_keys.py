"""Security contract tests for the isolated token primitives.

These tests do not enable bearer auth on any Django endpoint.
"""
from django.test import SimpleTestCase

from core.device_api_keys import (
    SCOPES,
    generate_token,
    parse_identifier,
    validate_scopes,
    verify_token,
)


class TokenPrimitiveTests(SimpleTestCase):
    def test_generated_tokens_are_random_and_verifiable(self):
        first = generate_token()
        second = generate_token()
        self.assertNotEqual(first.plaintext, second.plaintext)
        self.assertNotEqual(first.identifier, second.identifier)
        self.assertNotEqual(first.digest, second.digest)
        self.assertEqual(parse_identifier(first.plaintext), first.identifier)
        self.assertTrue(verify_token(first.plaintext, first.digest))
        self.assertFalse(verify_token(second.plaintext, first.digest))
        self.assertNotIn(first.plaintext, first.digest)

    def test_malformed_tokens_fail_closed(self):
        issued = generate_token()
        for invalid in (None, "", "mvk_abc", "Bearer " + issued.plaintext,
                        issued.plaintext[:-1], issued.plaintext + "x",
                        issued.plaintext.replace("mvk_", "bad_", 1)):
            with self.subTest(value=str(invalid)[:30]):
                self.assertIsNone(parse_identifier(invalid))
                self.assertFalse(verify_token(invalid, issued.digest))

    def test_invalid_digest_fails_closed(self):
        issued = generate_token()
        for value in ("", "0", None, "g" * 64, "A" * 64):
            with self.subTest(digest=value):
                self.assertFalse(verify_token(issued.plaintext, value))

    def test_scope_allowlist_and_canonical_order(self):
        self.assertIn("tags:read", SCOPES)
        self.assertEqual(
            validate_scopes(["tags:write", "tags:read"]),
            ("tags:read", "tags:write"),
        )
        for invalid in ([], "tags:read", ["admin:*"], ["tags:read", "tags:read"],
                        ["tags:read", 123], None):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    validate_scopes(invalid)
