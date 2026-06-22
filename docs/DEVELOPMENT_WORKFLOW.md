# Motionmate Development Workflow

Motionmate is currently live for a small private tester group. During this cycle, keep the deployed app stable and move new feature work off the production line until it is ready to promote.

## Branch roles

- `main`: production and private-test stable branch. Only release-ready commits and production hotfixes should land here.
- `develop`: preferred shared integration branch for local or staging feature work, if the team is using one.
- `feature/*`: scoped feature branches for new work. Create them from `develop` when `develop` is active.
- `hotfix/*`: minimal production bug-fix branches. Create them from `main`.
- If the team is not actively using a shared `develop` branch, keep feature work on isolated `feature/*` branches and do not merge to `main` until the release checklist is complete.
- This repository currently shows both `develop` and `development` branch variants in Git history and remotes. Standardize on one shared integration branch name before active feature work resumes. This guide uses `develop`.

## Day-to-day feature flow

1. Update your local clone and switch to `develop`, if your team is using it.
2. Create a new `feature/<short-name>` branch for one focused change set.
3. Build and test locally before opening or sharing the branch.
4. Merge approved feature work back into `develop`.
5. Keep `main` untouched until the release checklist is complete.

## Common local development commands

Install dependencies:

```bash
uv sync --extra dev
```

Run migrations:

```bash
uv run --no-sync python src/manage.py migrate
```

Start the local server:

```bash
uv run --no-sync python src/manage.py runserver
```

Run a targeted app test module:

```bash
uv run --no-sync python src/manage.py test apps.businesses.tests
```

Run a more targeted test case:

```bash
uv run --no-sync python src/manage.py test apps.businesses.tests.BusinessSettingsViewTests
```

Run the migration drift check:

```bash
uv run --no-sync python src/manage.py makemigrations --check --dry-run
```

Run the current main app suite:

```bash
uv run --no-sync python src/manage.py test apps.crm.tests apps.accounts.tests apps.businesses.tests apps.billings.tests
```

## Release checklist

Before merging `develop` or completed `feature/*` work into `main`:

- tests pass
- `makemigrations --check --dry-run` passes
- migrations are reviewed
- smoke tests pass locally
- smoke tests pass on staging or the private-test environment
- no production-only config is broken
- tester feedback issues and known regressions are reviewed

## Hotfix checklist

For a production bug fix during the private-tester cycle:

- branch from `main`
- reproduce and fix the minimal issue only
- run the smallest useful test set plus a quick smoke pass
- merge the hotfix branch back into `main`
- deploy `main`
- verify the live private-test app
- merge the updated `main` back into `develop`

## Promotion rule

- New product work should stay on `develop` and `feature/*` branches until it is intentionally promoted.
- `main` should remain deployable for private testers at all times.
- Production should receive hotfixes only while the current tester group is evaluating the live foundation.
