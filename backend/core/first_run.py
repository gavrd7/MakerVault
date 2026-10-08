"""One-time operator-authorised first administrator setup."""
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.db import connection, transaction
from django import forms

TOKEN_LIFETIME = 30 * 60


def token_path():
    return Path(os.getenv("MAKERVAULT_SETUP_TOKEN_FILE", "/app/keys/first_run_setup.json"))


def needs_setup():
    return not get_user_model().objects.filter(is_superuser=True).exists()


def create_token():
    if not needs_setup():
        raise ValueError("An administrator already exists; first-run setup is closed.")
    token = secrets.token_urlsafe(32)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"digest": hashlib.sha256(token.encode()).hexdigest(), "expires": int(time.time()) + TOKEN_LIFETIME}
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(payload, stream)
    os.replace(temporary, path)
    return token


def token_valid(token):
    try:
        payload = json.loads(token_path().read_text(encoding="utf-8"))
        return (int(payload["expires"]) >= time.time()
                and hmac.compare_digest(payload["digest"], hashlib.sha256(token.encode()).hexdigest()))
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return False


class InitialAdminForm(forms.Form):
    token = forms.CharField(label="One-time setup token", widget=forms.PasswordInput(attrs={"autocomplete": "off"}), max_length=256)
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        values = super().clean()
        if values.get("password1") != values.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        if values.get("username") and get_user_model().objects.filter(username=values["username"]).exists():
            self.add_error("username", "This username is already in use.")
        if values.get("password1"):
            try:
                password_validation.validate_password(values["password1"])
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
            except Exception as exc:
                from django.core.exceptions import ValidationError
                if isinstance(exc, ValidationError):
                    self.add_error("password1", exc)
                else:
                    raise
        return values


def establish_initial_admin(data):
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1935753101])
        if not needs_setup():
            raise ValueError("Administrator setup has already completed.")
        if not token_valid(data["token"]):
            raise ValueError("Setup token is invalid or expired.")
        user = get_user_model().objects.create_superuser(
            username=data["username"], email=data["email"], password=data["password1"]
        )
        # Removing the token prevents reuse. A superuser also permanently disables this flow.
        token_path().unlink(missing_ok=True)
        return user
