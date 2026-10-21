from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent.parent


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def translate_path(self, path):
        """Serve the demo and its source-imported SDK modules safely.

        The demo is intentionally dependency-free and imports the participant
        SDK directly from ``/packages``.  SimpleHTTPRequestHandler otherwise
        confines all requests to ``apps/participant-demo`` and returns 404 for
        those modules, which prevents the module entry point from running.
        Only the explicit repository packages subtree is exposed; all other
        paths retain the demo directory behavior.
        """
        relative = path.split("?", 1)[0].lstrip("/")
        if relative == "packages" or relative.startswith("packages/"):
            requested = (REPOSITORY_ROOT / relative).resolve()
            packages_root = (REPOSITORY_ROOT / "packages").resolve()
            if requested == packages_root or packages_root in requested.parents:
                return str(requested)
        if relative == "mediapipe" or relative.startswith("mediapipe/"):
            requested = (REPOSITORY_ROOT / "packages" / "gaze-provider-webgazer" / "smoke-test" / relative).resolve()
            asset_root = (REPOSITORY_ROOT / "packages" / "gaze-provider-webgazer" / "smoke-test" / "mediapipe").resolve()
            if requested == asset_root or asset_root in requested.parents:
                return str(requested)
        return super().translate_path(path)

    def end_headers(self):
        # This is a development server.  Do not let browser-cached ES modules
        # hide local SDK/demo changes during an integration run.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5173"))
    print(f"Participant demo: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), DemoHandler).serve_forever()
