"""Entry point executed only with clean env and copied application source."""

import json
import os
import sys
from pathlib import Path

from ui_preview.core import load_session, verify_database, verify_source


def main():
    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    name = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    verify_source(state[name]["source"])
    verify_database(root, state, name)
    import django

    django.setup()
    from ui_preview.guard import install

    install()
    from django.core.management import call_command

    action = sys.argv[1]
    if action == "migrate":
        call_command("migrate", interactive=False)
    elif action == "seed":
        from ui_preview.fixtures import seed

        result = seed(state)
        from ui_preview.core import write_json

        write_json(Path(state[name]["directory"]) / "fixtures.json", result)
        print(json.dumps(result, indent=2))
    elif action == "serve":
        call_command("runserver", f"127.0.0.1:{state[name]['http_port']}", use_reloader=False)
    elif action == "inspect":
        from ui_preview.fixtures import inventory

        print(json.dumps(inventory(), indent=2))
    else:
        raise RuntimeError("Unknown private runtime action.")


if __name__ == "__main__":
    main()
