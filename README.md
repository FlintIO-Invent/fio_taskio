# Project Title

**Project Description** 

### What it produces (quick bullets)


###  It’s designed to grow into:

## Dependency 

---

## Repo structure (already created)

### `src/project_name/` modules
- **Example/** *(build/simplify/edge attributes)*
- **Example/**  *(OD generation)*
- **Example/**  *(BPR + MSA + metrics)*
-

### `scripts/` runnable entry points
- **Example/**  *(OSMnx → GraphML)*
- **Example/**  *(bottlenecks + fragility)*

### Tests + docs
- **tests/** *(basic unit tests for assignment + metrics)*
- **docs/ARCHITECTURE.md** *(quick overview)*


## Quick start (uv)

```bash
# 1) Create venv + install core + dev tools
uv sync --extra dev --extra  --extra  --extra  --extra 

# 4) Run Graph Baselines for various experimentrs
uv run python scripts/example.py

---

# SXM Mobility Graph Lab — Step-by-Step Project Overview


## Key concepts


## Pipeline steps (in order)

- http://127.0.0.1:8000/home/
- http://127.0.0.1:8000/accounts/agent_login
- sudo fuser -k 8000/tcp






python manage.py makemigrations crm --empty --name seed_service_categories

from django.db import migrations


def seed_service_categories(apps, schema_editor):
    ServiceCategory = apps.get_model("crm", "ServiceCategory")

    defaults = [
        ("SEPTIC_PUMPING", "Septic Pumping"),
        ("SEPTIC_INSTALLATION", "Septic Installation"),
        ("SEPTIC_REPAIR", "Septic Repair"),
        ("GREASE_TRAP_SERVICES", "Grease Trap Services"),
        ("UNCLOGGING_SERVICES", "Unclogging Services"),
        ("OTHER", "Other"),
    ]

    for code, name in defaults:
        ServiceCategory.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )


def unseed_service_categories(apps, schema_editor):
    ServiceCategory = apps.get_model("crm", "ServiceCategory")
    codes = [
        "SEPTIC_PUMPING",
        "SEPTIC_INSTALLATION",
        "SEPTIC_REPAIR",
        "GREASE_TRAP_SERVICES",
        "UNCLOGGING_SERVICES",
        "OTHER",
    ]
    ServiceCategory.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        # IMPORTANT: replace with your latest crm migration
        ("crm", "00xx_previous_migration"),
    ]

    operations = [
        migrations.RunPython(seed_service_categories, reverse_code=unseed_service_categories),
    ]