"""Real Redis multi-process checks; use an isolated prefix, never flush a cache.

Run with TRACKING_REDIS_TEST_URL pointing at a disposable/test Redis service.
The URL is inherited by subprocesses and never included in their command lines.
"""

import json
import os
import subprocess
import sys
import uuid
from unittest import skipUnless

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings
from django.utils.crypto import salted_hmac

from .public_tracking import LOOKUP_LIMIT, allow_tracking_lookup


@skipUnless(os.environ.get("TRACKING_REDIS_TEST_URL"), "Requires an actual Redis test endpoint")
class TrackingSharedCacheTests(SimpleTestCase):
    @override_settings(
        LOGISTICS_TRACKING_CACHE_ALIAS="default",
        LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=True,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://127.0.0.1:1/0",
                "OPTIONS": {"socket_connect_timeout": 0.1, "socket_timeout": 0.1},
            }
        },
    )
    def test_unreachable_shared_cache_fails_closed(self):
        self.assertFalse(allow_tracking_lookup("192.0.2.77"))

    def test_atomic_limit_across_four_independent_processes(self):
        prefix = "tracking-acceptance-" + uuid.uuid4().hex
        secret = uuid.uuid4().hex
        config = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "logistics_tracking": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": os.environ["TRACKING_REDIS_TEST_URL"],
                "KEY_PREFIX": prefix,
                "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
            },
        }
        code = """
import json, os
from unittest.mock import patch
import django
django.setup()
from django.test import override_settings
from apps.logistics.public_tracking import allow_tracking_lookup
with override_settings(CACHES=json.loads(os.environ['TRACKING_TEST_CACHES']),
                       SECRET_KEY=os.environ['TRACKING_TEST_SECRET'],
                       LOGISTICS_TRACKING_CACHE_ALIAS='logistics_tracking',
                       LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=True):
    with patch('apps.logistics.public_tracking.time.time', return_value=120):
        result=[allow_tracking_lookup('192.0.2.77') for _ in range(10)]
print(json.dumps(result))
"""
        env = os.environ.copy()
        env.update(
            DJANGO_SETTINGS_MODULE="taskio.settings",
            TRACKING_TEST_CACHES=json.dumps(config),
            TRACKING_TEST_SECRET=secret,
        )
        with override_settings(CACHES=config, SECRET_KEY=secret):
            shared = caches["logistics_tracking"]
            peer = salted_hmac("logistics.public_tracking.peer", "192.0.2.77").hexdigest()
            key = f"logistics:public-tracking:2:{peer}"
            workers = []
            try:
                workers = [
                    subprocess.Popen(
                        [sys.executable, "-c", code],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    for _ in range(4)
                ]
                accepted = []
                for worker in workers:
                    stdout, _stderr = worker.communicate(timeout=45)
                    self.assertEqual(
                        worker.returncode, 0, "Cache worker failed; no credentials logged"
                    )
                    accepted.extend(json.loads(stdout.strip().splitlines()[-1]))
                self.assertEqual(sum(accepted), LOOKUP_LIMIT)
                self.assertEqual(len(accepted), 40)
                self.assertEqual(shared.get(key), 40)
                client = shared._cache.get_client(key)
                self.assertGreater(client.ttl(shared.make_key(key)), 0)
                self.assertLessEqual(client.ttl(shared.make_key(key)), 120)
            finally:
                for worker in workers:
                    if worker.poll() is None:
                        worker.kill()
                        worker.communicate()
                shared.delete(key)
                shared.close()
