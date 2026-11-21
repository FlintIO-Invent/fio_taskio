"""Preview-only integration/network/connection guards; no application policy changes."""

import json
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.db.backends.signals import connection_created
from django.http import HttpResponse, JsonResponse


class PreviewWriteBlocked(RuntimeError):
    pass


def audit(event):
    with (Path(settings.SIDE["directory"]) / "blocked.jsonl").open("a") as stream:
        stream.write(json.dumps(event) + "\n")


def network_guard():
    original_dns = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def dns(host, *args, **kwargs):
        if host not in {None, "localhost", "127.0.0.1", "::1"}:
            audit({"kind": "network", "operation": "dns", "host": str(host)})
            raise RuntimeError("External networking is disabled in this local preview.")
        return original_dns(host, *args, **kwargs)

    def address_allowed(address):
        if isinstance(address, tuple) and (
            address[0] != "127.0.0.1" or address[1] != settings.SIDE["port"]
        ):
            audit(
                {
                    "kind": "network",
                    "operation": "connect",
                    "host": str(address[0]),
                    "port": address[1],
                }
            )
            raise RuntimeError("Only this preview's PostgreSQL listener is reachable from Django.")

    def connect(sock, address):
        address_allowed(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        address_allowed(address)
        return original_connect_ex(sock, address)

    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = dns, connect, connect_ex


def connection_guard(sender, connection, **kwargs):
    expected = settings.SIDE
    configured = connection.settings_dict
    if (configured["HOST"], str(configured["PORT"]), configured["NAME"]) != (
        "127.0.0.1",
        str(expected["port"]),
        expected["database"],
    ):
        raise RuntimeError("Django attempted an unowned database connection.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT host(inet_server_addr()), inet_server_port(), current_setting('data_directory'), (SELECT system_identifier::text FROM pg_control_system()), current_database()"
        )
        actual = cursor.fetchone()
    if actual != (
        "127.0.0.1",
        expected["port"],
        expected["data_directory"],
        expected["system_identifier"],
        expected["database"],
    ):
        connection.close()
        raise RuntimeError("Django's live PostgreSQL identity differs from the private preview.")
    if (
        os.environ["MOTIONMATE_PREVIEW_PHASE"] == "serve"
        and runtime_writes not in connection.execute_wrappers
    ):
        connection.execute_wrappers.append(runtime_writes)


def runtime_writes(execute, sql, params, many, context):
    text = str(sql).strip()
    write = re.match(r"(?:INSERT|UPDATE|DELETE|MERGE)\b", text, re.I)
    ddl = re.match(r"(?:CREATE|ALTER|DROP|TRUNCATE|COPY|DO|GRANT)\b", text, re.I)
    financial = re.search(
        r"\b(?:billings_[a-z_]+|businesses_businesssubscription|businesses_clarivoplan|logistics_logisticscharge)\b",
        text,
        re.I,
    )
    # Capacity-managed invitation expiry uses read-only subscription joins.
    # Allow only a single ORM invitation UPDATE with no nested write/DDL.
    invitation = re.match(r'^UPDATE\s+"businesses_businessinvitation"\s+SET\s+', text, re.I)
    safe_invitation_update = bool(
        invitation
        and ";" not in text
        and "--" not in text
        and "/*" not in text
        and not re.search(
            r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|COPY|DO|GRANT)\b",
            text[invitation.end() :],
            re.I,
        )
    )
    if ddl or (write and financial and not safe_invitation_update):
        audit({"kind": "financial-write", "operation": text.split()[0]})
        raise PreviewWriteBlocked(
            "Financial/platform subscription writes and schema operations are unavailable in a UI preview."
        )
    return execute(sql, params, many, context)


def install():
    network_guard()
    connection_created.connect(
        connection_guard, weak=False, dispatch_uid="motionmate_preview_identity"
    )


class PreviewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/_preview/"):
            response = self.local_resource(request)
        elif request.path.startswith("/billing/") or (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and (request.path.startswith("/billings/") or "/billing/" in request.path)
        ):
            audit({"kind": "disabled-route", "path": request.path, "method": request.method})
            response = HttpResponse(
                "Billing/provider operations are disabled in this disposable local preview. No operation was performed.",
                status=409,
                content_type="text/plain",
            )
        else:
            response = self.get_response(request)
        if response.get("Location"):
            target = urlparse(response["Location"])
            if target.netloc and target.netloc != f"127.0.0.1:{settings.SIDE['http_port']}":
                response = HttpResponse(
                    "External redirects are disabled in this preview.",
                    status=409,
                    content_type="text/plain",
                )
        if response.get("Content-Type", "").startswith("text/html") and not response.streaming:
            # Local copy of the same Nunito family; no synthetic UI/controller.
            text = response.content.decode(response.charset)
            text = re.sub(
                r'<link\b[^>]*\brel=["\'](?:preconnect|dns-prefetch)["\'][^>]*>',
                "",
                text,
                flags=re.I,
            )
            text = re.sub(r'https://fonts\.googleapis\.com/[^"\s>]+', "/_preview/nunito.css", text)

            def external_link(match):
                target = urlparse(match[2])
                if (
                    target.scheme in {"http", "https"}
                    and target.netloc == f"127.0.0.1:{settings.SIDE['http_port']}"
                ):
                    return match[0]
                return match[1] + "/_preview/disabled-external" + match[3]

            text = re.sub(
                r'(<a\b[^>]*\bhref=["\'])((?:https?://|mailto:|tel:)[^"\']*)(["\'])',
                external_link,
                text,
                flags=re.I,
            )
            response.content = text.encode(response.charset)
            if "Content-Length" in response:
                response["Content-Length"] = len(response.content)
        response["Cache-Control"] = "no-store"
        response["X-Motionmate-Preview"] = settings.SIDE_NAME
        response["Content-Security-Policy"] = (
            "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self'; form-action 'self'; frame-src 'none'; object-src 'none'; worker-src 'none'; base-uri 'self'"
        )
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, PreviewWriteBlocked):
            return HttpResponse(str(exception), status=409, content_type="text/plain")

    def local_resource(self, request):
        if request.method not in {"GET", "HEAD"}:
            return HttpResponse(status=405)
        if request.path == "/_preview/disabled-external":
            return HttpResponse(
                "External links/integrations are unavailable in this local preview.",
                status=409,
                content_type="text/plain",
            )
        if request.path == "/_preview/nunito.css":
            return HttpResponse(
                "@font-face{font-family:'Nunito Sans';font-style:normal;font-weight:200 1000;font-display:swap;src:url('/_preview/nunito.woff2') format('woff2')}",
                content_type="text/css",
            )
        if request.path == "/_preview/nunito.woff2":
            return HttpResponse(
                (settings.ROOT / "vendor/nunito.woff2").read_bytes(), content_type="font/woff2"
            )
        if request.path == "/_preview/health":
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                database = cursor.fetchone()[0]
            return JsonResponse(
                {
                    "side": settings.SIDE_NAME,
                    "session": settings.SESSION["id"],
                    "database": database,
                    "source": str(settings.SOURCE),
                    "source_sha256": json.loads((settings.SOURCE / "source.json").read_text())[
                        "sha256"
                    ],
                    "cookie_name": settings.SESSION_COOKIE_NAME,
                    "csrf_cookie_name": settings.CSRF_COOKIE_NAME,
                    "providers": False,
                    "financial_writes": False,
                    "email_backend": settings.EMAIL_BACKEND,
                    "fixtures": json.loads(
                        (Path(settings.SIDE["directory"]) / "fixtures.json").read_text()
                    ),
                }
            )
        return HttpResponse(status=404)
