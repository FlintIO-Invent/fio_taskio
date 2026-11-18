"""Read-only preservation proof for approved source and owned fixture records."""

import hashlib
import json
from pathlib import Path

import psycopg2
from psycopg2 import sql
from ui_preview.core import load_session, verify_database, verify_source

TASK = Path(__file__).resolve().parent
REPO = TASK.parents[4]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def main():
    state = json.loads((TASK / "state.json").read_text())
    approved = {f["path"] for f in state["manifest"]}
    baseline = json.loads((TASK / "preservation-before.json").read_text())["files"]
    unexpected = [
        name
        for name, expected in baseline.items()
        if name not in approved
        and (
            not (REPO / name).is_file()
            or hashlib.sha256((REPO / name).read_bytes()).hexdigest() != expected
        )
    ]
    assert not unexpected, unexpected
    design_changed = [
        name
        for name, expected in state["design_artifacts"].items()
        if hashlib.sha256((REPO / name).read_bytes()).hexdigest() != expected
    ]
    assert not design_changed, design_changed
    root, runtime = load_session("/tmp/motionmate-preview-session-p29z5cgt")
    records, identities, sources, raw = {}, {}, {}, {}
    fixture = json.loads((root / "before/fixtures.json").read_text())
    original_clients = [r["id"] for r in fixture["inventory"]["crm.Client"]]
    tables = [
        "crm_client",
        "billings_invoice",
        "billings_invoiceline",
        "billings_invoicepayment",
        "billings_invoiceobligationshare",
        "billings_invoicereceiptshare",
        "billings_parcelcancellationsettlement",
        "billings_invoicecancellationcredit",
        "billings_invoicerefundallocation",
    ]
    for side in ("before", "after"):
        verify_source(runtime[side]["source"])
        sources[side] = json.loads((Path(runtime[side]["source"]) / "source.json").read_text())[
            "sha256"
        ]
        identities[side] = verify_database(root, runtime, side)
        config = runtime[side]
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["database"],
            user=runtime["db_user"],
            connect_timeout=3,
        )
        conn.set_session(readonly=True)
        try:
            records[side] = {}
            raw[side] = {}
            with conn.cursor() as c:
                for table in tables:
                    query = sql.SQL("SELECT row_to_json(t) FROM {} t").format(sql.Identifier(table))
                    if table == "crm_client":
                        query += sql.SQL(" WHERE id = ANY(%s)")
                        params = (original_clients,)
                    else:
                        params = ()
                    query += sql.SQL(" ORDER BY id")
                    c.execute(query, params)
                    rows = [r[0] for r in c.fetchall()]
                    # Passwords/sessions are never selected. Generated receipt retry UUIDs
                    # and receipt creation times differ between equivalent fixture setups; compare financial facts.
                    ignored = {"created_at", "updated_at", "idempotency_key", "recorded_at"}
                    rows = [
                        {key: value for key, value in row.items() if key not in ignored}
                        for row in rows
                    ]
                    raw[side][table] = rows
                    records[side][table] = {"count": len(rows), "sha256": digest(rows)}
        finally:
            conn.close()
    if records["before"] != records["after"]:
        for table in tables:
            left, right = raw["before"][table], raw["after"][table]
            if left != right:
                print(table, "counts", len(left), len(right))
                for a, b in zip(left, right, strict=False):
                    if a != b:
                        print(
                            "ID", a["id"], "changed fields", [key for key in a if a[key] != b[key]]
                        )
        raise AssertionError("Original records or financial facts changed.")
    after_root = Path(runtime["after"]["source"])
    runtime_files = [name for name in approved if name.startswith("src/")]
    assert all(
        (REPO / name).read_bytes() == (after_root / name).read_bytes() for name in runtime_files
    ), "AFTER source differs from candidate."
    result = dict(
        protected_files=len(baseline),
        protected_outside_manifest_unchanged=True,
        approved_design_artifacts_unchanged=len(state["design_artifacts"]),
        manifest_files=len(approved),
        runtime_candidate_files=len(runtime_files),
        runtime_matches_candidate=True,
        source_identities=sources,
        database_identities=identities,
        original_client_records=len(original_clients),
        original_and_financial_records=records,
        original_records_equal=True,
        excluded_setup_metadata=["created_at", "updated_at", "idempotency_key", "recorded_at"],
        ordinary_database_access=False,
    )
    (TASK / "final-preservation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"original_and_financial_records", "database_identities"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
