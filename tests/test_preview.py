from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preview.py"


def load_preview():
    spec = importlib.util.spec_from_file_location("preview", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preview = load_preview()

    def test_help_is_friendly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Preview the built website", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_arguments_are_rejected(self) -> None:
        for arguments in (["nope"], ["0"], ["65536"], ["8000", "extra"]):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                self.preview.parse_args(arguments)

    def test_build_uses_the_active_python(self) -> None:
        with mock.patch.object(self.preview.subprocess, "run") as run:
            self.preview.build_site()

        run.assert_called_once_with(
            [sys.executable, str(ROOT / "scripts" / "build.py")], check=True
        )

    def test_server_is_local_and_serves_every_route(self) -> None:
        self.preview.build_site()
        server = self.preview.create_server(port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        host, port = server.server_address

        try:
            self.assertEqual(host, "127.0.0.1")
            for route in (
                "/",
                "/writing.html",
                "/research.html",
                "/about.html",
                "/fun.html",
                "/cv.html",
                "/style.css",
            ):
                with (
                    self.subTest(route=route),
                    urlopen(f"http://{host}:{port}{route}", timeout=5) as response,
                ):
                    self.assertEqual(response.status, 200)

            self.preview.build_site()
            with urlopen(f"http://{host}:{port}/writing.html", timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
