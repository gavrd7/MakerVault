# Accounts and storage

**For the installation administrator**

## Add a local user

1. Sign in as a superuser and open **Administration**.
2. Open **Users** and add a user with a unique username and strong initial password.
3. Save the user, then open **Settings → Users & storage** to assign the appropriate role.
4. Choose Admin, Supervisor, User or Viewer using the role selector.
5. Keep **Active** enabled. Admin is reserved for trusted full-instance administrators.
6. Ask the person to sign in and change their initial password through **Settings → User Account**.

A group grants actions, not ownership of another person's workspace. The default Editor group includes view/add/change core permissions and inventory deletion; it does not grant every delete action. A button may be absent because a specific permission is missing.

Local self-registration is disabled by default. Enabling `ALLOW_LOCAL_REGISTRATION` is a separate administrative decision. OIDC provisioning is configured separately and does not mean a new identity should automatically become an administrator.

## Change user roles

A superuser can manage roles at any time under **Settings → Users & storage → Users**.

- **Admin:** full instance access, including account administration, HTTPS, OIDC, security and backups.
- **Supervisor:** operational settings (library updates and 3D printing integrations), without administrator, HTTPS, OIDC, backups or user-management access.
- **User:** personal account settings and standard workspace access.
- **Viewer:** read-only workspace access and personal account settings.

The existing Editor group is retained for installations that already use it. The new User and Supervisor role presets use the existing workspace editing permissions, while server-wide settings require separate authorization. Roles restrict which settings can be *used* as well as which sections appear; hiding a tab alone is not a security boundary. A newly changed role takes effect on subsequent authenticated requests; reload the app to refresh its navigation.

Only a superuser can assign roles. MakerVault rejects attempts to demote the current administrator or the last active superuser.

## Sign-in methods and account linking

Each signed-in user can open **Settings → User Account → Connected sign-in methods** to see external identities linked to their MakerVault account and any configured identity providers available to connect.

Linking an OIDC identity does not create a second MakerVault workspace: it adds another way to sign in to the same account. Removing a linked identity removes only that sign-in route. MakerVault blocks removal when it would leave the user with neither a usable local password nor another external sign-in connection.

Administrators configure which OIDC providers exist under **Settings → Security → OIDC identity providers**. That administration screen and the per-user **Sign-in methods** screen serve different purposes.

## What is shared?

Shared catalogue/reference records describe products. Personal inventory, projects, files, printers, spools, models, print history and integration settings are owner-scoped. Current project workspaces are not a general team-sharing system.

The normal administration summary exposes aggregate counts and storage, not a cross-user project/file browser. Nevertheless, the server operator controls the database, code, backups and storage key. Encryption at rest is not end-to-end encryption against that operator.

## Set quotas

As a superuser, open **Settings → Users & storage**. Review each account's status, aggregate record counts and usage.

- **Default policy:** Limited or Unlimited for users following the instance default.
- **Instance default:** the account follows the current default policy.
- **Custom limit:** a per-user quota in GiB.
- **Unlimited:** no application-level quota for that account.

Save the policy or the user's quota with its corresponding button. New installations default to unlimited storage in this edition. A quota is not reserved disk space: all users still share the host's physical capacity.

Usage includes retained files/versions and private images. Lowering a quota does not automatically delete existing files. If an upload is refused, inspect current usage, the requested file size and host free space. Consider exporting wanted versions before removing data.

## Disable, purge and delete

**Disable** blocks account use while preserving data and can be reversed. It is the usual first action when access should stop.

**Purge private data** removes that user's private workspace but preserves the account. **Delete account** removes the account and its private data. These require typing the exact username and have no ordinary undo. The UI blocks self-disable/self-purge/self-delete.

Confirm the user and make a restorable backup before either destructive operation. Shared catalogue information is not that user's private workspace to purge.
