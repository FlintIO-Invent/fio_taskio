"""Offline checks for the Heroku age installer, startup PATH, and handoff wrapper."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class AgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.env = {**os.environ, "PATH": f"{self.tools}:/usr/bin:/bin"}
        for script in ("install_age.sh", "logistics_test_lab_handoff.sh"):
            shutil.copyfile(REPO / "scripts" / script, self.root / "scripts" / script)

    def tool(self, name, body):
        path = self.tools / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_script(self, name, *args):
        return subprocess.run(
            ["/bin/bash", str(self.root / "scripts" / name), *args],
            env=self.env,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_checksum_mismatch_refuses_installation_for_both_architectures(self):
        self.tool(
            "curl",
            'printf "%s\\n" "$*" > "$LAB_TEST_CURL_LOG"\nwhile (( $# )); do\n  if [[ $1 == --output ]]; then printf corrupt > "$2"; exit 0; fi\n  shift\ndone\nexit 1\n',
        )
        self.env["LAB_TEST_CURL_LOG"] = str(self.root / "curl.log")
        for machine, asset in (("x86_64", "amd64"), ("aarch64", "arm64")):
            with self.subTest(machine=machine):
                self.tool("uname", f"if [[ $1 == -s ]]; then echo Linux; else echo {machine}; fi\n")
                result = self.run_script("install_age.sh")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / ".heroku/age/bin").exists())
                self.assertIn(
                    f"https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-{asset}.tar.gz",
                    (self.root / "curl.log").read_text(),
                )

    def test_download_failure_refuses_installation(self):
        self.tool("curl", "exit 22\n")
        result = self.run_script("install_age.sh")
        self.assertEqual(result.returncode, 22)
        self.assertFalse((self.root / ".heroku/age/bin").exists())

    def test_unsupported_platform_refuses_before_download(self):
        self.tool("curl", 'touch "$LAB_TEST_DOWNLOAD_MARKER"\n')
        self.env["LAB_TEST_DOWNLOAD_MARKER"] = str(self.root / "downloaded")
        for system, machine in (("Darwin", "arm64"), ("Linux", "unknown")):
            with self.subTest(system=system, machine=machine):
                self.tool(
                    "uname", f"if [[ $1 == -s ]]; then echo {system}; else echo {machine}; fi\n"
                )
                self.assertNotEqual(self.run_script("install_age.sh").returncode, 0)
                self.assertFalse((self.root / "downloaded").exists())

    def test_buildpack_hook_propagates_installation_failure_from_any_directory(self):
        (self.root / "bin").mkdir()
        shutil.copyfile(REPO / "bin/post_compile", self.root / "bin/post_compile")
        (self.root / "scripts/install_age.sh").write_text("#!/usr/bin/env bash\nexit 42\n")
        result = subprocess.run(
            ["bash", str(self.root / "bin/post_compile")],
            cwd=self.tools,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 42)

    def test_profile_exports_slug_bin_for_each_dyno_type(self):
        for dyno in ("web.1", "release.1", "run.1234"):
            with self.subTest(dyno=dyno):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; printf "%s" "$PATH"',
                        "bash",
                        str(REPO / ".profile.d/age.sh"),
                    ],
                    env={**self.env, "DYNO": dyno},
                    cwd=self.tools,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                self.assertTrue(
                    result.stdout.startswith(str(Path.home() / ".heroku/age/bin") + ":")
                )

    def test_handoff_requires_explicit_execute_before_running_application(self):
        self.tool("python", 'touch "$LAB_TEST_APPLICATION_MARKER"\n')
        self.env["LAB_TEST_APPLICATION_MARKER"] = str(self.root / "application-ran")
        result = self.run_script("logistics_test_lab_handoff.sh", "--initialize")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / "application-ran").exists())

    def test_missing_age_refuses_before_running_application(self):
        self.tool("python", 'touch "$LAB_TEST_APPLICATION_MARKER"\n')
        self.env["LAB_TEST_APPLICATION_MARKER"] = str(self.root / "application-ran")
        self.env["PATH"] = str(self.tools)
        result = self.run_script("logistics_test_lab_handoff.sh", "--execute")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / "application-ran").exists())

    @unittest.skipUnless(
        (REPO / ".heroku/age/bin/age").exists(), "Run scripts/install_age.sh first."
    )
    def test_handoff_emits_only_decryptable_ciphertext_and_removes_dyno_artifact(self):
        age_bin = REPO / ".heroku/age/bin"
        key = self.root / "test-identity"
        subprocess.run(
            [str(age_bin / "age-keygen"), "-o", str(key)], capture_output=True, check=True
        )
        recipient = subprocess.run(
            [str(age_bin / "age-keygen"), "-y", str(key)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.env["PATH"] = f"{self.tools}:{age_bin}:/usr/bin:/bin"
        self.env["LAB_TEST_RECIPIENT"] = recipient
        self.env["LAB_TEST_ARTIFACT_LOG"] = str(self.root / "artifact-path")
        self.tool(
            "python",
            'echo "management-inventory"\nwhile (( $# )); do\n'
            "  if [[ $1 == --credential-file ]]; then\n"
            '    printf "%s" "$2" > "$LAB_TEST_ARTIFACT_LOG"\n'
            '    printf "non-secret test handoff" | age --armor --recipient "$LAB_TEST_RECIPIENT" --output "$2"\n'
            "    exit 0\n  fi\n  shift\ndone\nexit 1\n",
        )
        result = self.run_script("logistics_test_lab_handoff.sh", "--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("management-inventory", result.stdout)
        self.assertIn("management-inventory", result.stderr)
        decrypted = subprocess.run(
            [str(age_bin / "age"), "--decrypt", "--identity", str(key)],
            input=result.stdout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(decrypted, "non-secret test handoff")
        artifact = Path((self.root / "artifact-path").read_text())
        self.assertFalse(artifact.exists())
        self.assertFalse(artifact.parent.exists())

    def test_handoff_refuses_missing_or_plaintext_artifact(self):
        self.tool("age", "exit 0\n")
        for body in (
            "exit 0\n",
            'while (( $# )); do\n  if [[ $1 == --credential-file ]]; then printf "plaintext-sentinel" > "$2"; exit 0; fi\n  shift\ndone\n',
        ):
            with self.subTest(body=body):
                self.tool("python", body)
                result = self.run_script("logistics_test_lab_handoff.sh", "--execute")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("plaintext-sentinel", result.stderr)

    def test_failed_management_command_emits_no_artifact(self):
        self.tool("age", "exit 0\n")
        self.tool("python", "exit 9\n")
        result = self.run_script("logistics_test_lab_handoff.sh", "--execute")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
