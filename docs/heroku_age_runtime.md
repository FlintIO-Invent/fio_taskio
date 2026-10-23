# Heroku age runtime and credential verification

Read-only deployment audit: `mm-development-app` uses the classic
`heroku/python` buildpack on `heroku-26`, branch `develop`. `Procfile` runs
migrations in the release phase and Gunicorn for web processes. The existing
`build.sh` runs uv/collectstatic; it is not the classic Python buildpack hook.
There was no Aptfile, custom buildpack, or age installation hook.

The smallest compatible addition is `bin/post_compile`, which invokes
`scripts/install_age.sh`. No buildpack/configuration changes, Python dependencies,
or Procfile changes are needed. Heroku's existing Python buildpack
[runs this hook](https://github.com/heroku/heroku-buildpack-python/blob/main/bin/compile).
`.profile.d/age.sh` puts `$HOME/.heroku/age/bin` on PATH at startup for web,
release and one-off dynos, using Heroku's
[profile mechanism](https://devcenter.heroku.com/articles/buildpack-api).

The installer downloads only official
[age v1.3.2 release assets](https://github.com/FiloSottile/age/releases/tag/v1.3.2)
over HTTPS. SHA-256 values are pinned from the upstream GitHub release API:

| Linux architecture | Archive SHA-256 |
| --- | --- |
| amd64 | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` |
| arm64 | `6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4` |

It verifies the archive before extraction/execution, checks both binaries report
`v1.3.2`, and installs `age` and `age-keygen` in the slug. Download, checksum,
platform or version failures fail the build. No runtime download or key generation
occurs. Version updates must deliberately update the version and both hashes.

Before account creation or password rotation, `credential_target()` checks a new
artifact path in a private owned directory, then encrypts non-secret probe input
with the supplied public recipient. This validates the recipient checksum and
actual CLI operation, armored output, and destination write/fsync availability.
Errors suppress provider diagnostics and create no accounts. Final encryption
and file-write failures still roll back the write transaction. The handoff wrapper
checks CLI availability before invoking Django and refuses missing or unarmored
artifacts. It emits only ciphertext on stdout and removes the dyno artifact on exit.

Database/app/environment confirmations, subscription/approval checks, normal seat
limits, ownership gates, Production rejection and SERVICE policies are unchanged.

## Deployment

Commit/review these changes on `develop`, then deploy the reviewed commit through
the existing Development deployment workflow. For an intentional manual Git
deployment from `develop`:

```bash
git push https://git.heroku.com/mm-development-app.git HEAD:main
```

No `heroku config:set`, additional buildpack, or account provisioning is required.
Expect `Installed verified age v1.3.2 (...)` in the build log. The existing release
phase continues to apply migrations normally. The new hook only takes effect in
a new build; restarting the old slug does not install age.

## Read-only verification after deployment

```bash
heroku buildpacks --app mm-development-app
heroku run --no-tty --exit-code --app mm-development-app \
  'command -v age && age --version && command -v age-keygen && age-keygen --version'

# Public age recipient only; replace the placeholder before running.
# The output is discarded and input is non-secret; no accounts are created.
heroku run --no-tty --exit-code --app mm-development-app \
  'printf "Motionmate encryption verification\n" | age --armor --recipient age1YOUR_PUBLIC_RECIPIENT --output /dev/null'

# Existing authorization/fixture preview: zero database writes.
heroku run --no-tty --exit-code --app mm-development-app \
  'python src/manage.py setup_logistics_test_lab --environment development --initialize'
```

Expected executable paths are `/app/.heroku/age/bin/age` and
`/app/.heroku/age/bin/age-keygen`; both report `v1.3.2`. The recipient probe must
exit zero. If a lab already exists, use `--inspect` instead of `--initialize`.
Never upload the operator's private identity to Heroku or print decrypted credentials.

## Focused local checks

```bash
bash scripts/install_age.sh
python3 scripts/test_age_runtime.py -v
PATH="$PWD/.heroku/age/bin:$PATH" ENV=development DEBUG=True DATABASE_URL='' \
  DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  LOGISTICS_LOCAL_BILLING_BYPASS=False \
  .venv/bin/python src/manage.py test apps.logistics.test_test_lab --noinput
bash -n bin/post_compile scripts/install_age.sh scripts/logistics_test_lab_handoff.sh .profile.d/age.sh
```

The local installation writes only ignored `.heroku/age` build artifacts. The
automated suite exercises recipient rejection before writes, missing/broken CLI,
destination failure, real encryption/decryption, final rollback, existing lab
authorization and SERVICE preservation. Installer/wrapper tests are offline;
the real pinned download and executable check are exercised by the installation.
Successful local checks do not prove a new slug has been deployed: run the above
one-off dyno verification after deployment.
