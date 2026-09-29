# Email and account recovery

**Advanced · Optional SMTP setup**

Email is disabled when `EMAIL_HOST` is empty. Password-reset messages are then not delivered, and reset links are not written to logs as a fallback.

## Configure SMTP

Use the values supplied by your mail provider:

```dotenv
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=YOUR-SMTP-USERNAME
EMAIL_HOST_PASSWORD=YOUR-SMTP-PASSWORD
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=MakerVault <makervault@example.com>
```

The example uses STARTTLS on port 587. Do not assume changing the port to 465 enables implicit TLS; the documented settings expose `EMAIL_USE_TLS`. Choose a compatible provider configuration.

Recreate the app with `sudo docker compose up -d`. Ensure the sending domain/address is authorised at the mail provider and that the host permits outbound SMTP. Test a password-reset request on an account you control; verify receipt and the correct HTTPS hostname in the link.

## Recover a local password without email

An authorised server operator can reset a local password interactively:

```bash
sudo docker compose exec makervault python manage.py changepassword USERNAME
```

Replace `USERNAME`. The prompt avoids putting the new password in shell history. This is not a general MFA-bypass procedure. Use saved MFA recovery codes or the authentication provider's supported recovery process as applicable.

If `MAKERVAULT_ADMIN_PASSWORD` remains configured, startup can reset that configured administrator's password again. Clear the bootstrap password after the initial setup if you want later interactive password changes to persist across restarts. The beginner guide avoids that bootstrap method.
