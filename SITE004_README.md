# SITE-004 — смартангар.рф: restricted public-email release candidate

This repo is public. Never commit private keys, server source archives, backup files, customer data, or mail/form recipient configuration.

## Approved public contacts

| Domain | Public email | SITE-004 change? |
| --- | --- | --- |
| smartangar.ru | Angarlp@yandex.ru | No |
| смартангар.рф (without hyphen) | smartangar@yandex.ru | Yes |
| смарт-ангар.рф (with hyphen) | Angarlp@yandex.ru | No |

The server-side form recipients and handlers, PHP, API, SMTP, and CRM remain unchanged. A separate issue SITE-002 covers the two-email concern on the hyphenated site.

## Included files

- server/site004_release.py — inventories .html/.htm files and supports prepare/publish/rollback **only after an exact-byte reviewed manifest** is installed. It checks the original SHA-256, refuses symlinks and unexpected file changes, preserves the original for rollback, and blocks form/script edits.
- server/site004_ssh_guard.py — permits exactly four fixed commands, no arbitrary shell. Install root-owned in a locked path and invoke only using a restricted authorized_keys command for an unprivileged site-deploy user.
- .github/workflows/site004-tests.yml — PR unit tests, no deployment.
- .github/workflows/site004-release.yml — manual workflow_dispatch, environment production-smartangar (required owner approval), not an automatic deployment.

## Required first: authorized technical Work / server administrator

1. Verify the **actual nginx configuration**, document root, ownership, form handlers, and public contact content for смартангар.рф; proposed root is /var/www/smartangar-rf/public_html. Do not assume the URL and directory match just from the name.
2. On SAM, install the two reviewed Python scripts as root-owned, user-non-writable files under /usr/local/libexec. Create an actual reviewed manifest in /etc/site-deploy/site004-manifest.json, owned by root. Do not use a manifest with dummy hashes, and do not send private customer data to public GitHub.
3. Grant site-deploy the *minimal* ownership and directory rename rights needed for **only reviewed HTML files**, not all /var/www, PHP, or other clients. Check backup parent /home/site-deploy and existing backups before setting up /home/site-deploy/site004-backup. Do not chown the whole document root.
4. Configure a dedicated site-deploy authorized_keys line with restrict and forced command /usr/local/libexec/site004_ssh_guard.py. The current SSH check key is restricted to check-smartangar and **does not authorize publishing**. Provision a distinct key, placing its private part only in protected GitHub Environment secret SAM_SSH_KEY. Keep trusted SAM_HOST and pinned SAM_HOST_FINGERPRINT settings.
5. With appropriate Environment approval, run inventory and prepare; verify hashes and private backup before approving a **separate** publish run. Then check all three public domains including cache bypass and the existing form-delivery route. Keep rollback enabled.
6. If live content is generated from PHP, CMS, Tilda, JavaScript, or templates rather than actual editable HTML files, stop — this HTML-only release candidate is unsuitable and needs a different reviewed implementation.

## Manifest format (illustrative only)

Do not use the placeholder SHA-256 below. Build the actual manifest from reviewed SAM files.

~~~json
{
  "domain": "смартангар.рф",
  "root": "/var/www/smartangar-rf/public_html",
  "files": [
    {
      "path": "index.html",
      "sha256": "REAL_64_CHARACTER_SHA256_OF_CURRENT_FILE",
      "edits": [{"before": "mailto:Angarlp@yandex.ru"}]
    }
  ]
}
~~~

The tool permits ONLY the exact replacement Angarlp@yandex.ru → smartangar@yandex.ru within a unique reviewed HTML fragment. It refuses to change any inline script, form or PHP source and requires source files to be owned by the unprivileged publisher.

## Tests and release status

Run as an **unprivileged** user:

~~~sh
python3 -m unittest discover -s tests -p 'test_site004_*.py' -v
~~~

11 local tests passed on synthetic HTML: inventory, backup, publish/rollback, unchanged form contents, bad manifest/hashes, symlink protection and guarded form/script replacement. That proves only the tested code path, **not** production access, actual HTML compatibility, delivery of leads, or publication. Merging this PR also does **not** install the server component. Never claim SITE-004 DONE until the real server and all sites are independently verified.
