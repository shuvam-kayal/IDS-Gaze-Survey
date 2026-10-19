from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent

class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5173"))
    print(f"Participant demo: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), DemoHandler).serve_forever()
