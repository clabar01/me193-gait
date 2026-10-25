"""Serve laptop/ over http so the dashboard can load its 3D avatar files.

Browsers block a page opened as a file (double-clicked) from loading other local
files such as laptop/assets/*.fbx, so the 3D avatar needs a local web server.
This is `python -m http.server --directory laptop --bind 127.0.0.1`, plus it
opens the dashboard in the browser. Only this computer can reach it.

    python laptop/serve.py                     # http://localhost:8000/dashboard.html
    python laptop/serve.py --port 8080 --no-open
    python laptop/serve.py --query "prefix=ME193/ceci/gait/test"   # simulator test topics

Ctrl+C stops it.
"""

import argparse
import functools
import http.server
import pathlib
import webbrowser

LAPTOP = pathlib.Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass                        # quiet: only errors are printed (log_error)

    def log_error(self, fmt, *args):
        print(f"serve.py: {fmt % args}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Serve the dashboard on localhost.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--query", default="", help="URL query for the dashboard, e.g. 'prefix=...&name=Ceci'")
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    args = ap.parse_args()

    handler = functools.partial(Handler, directory=str(LAPTOP))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://localhost:{args.port}/dashboard.html" + (f"?{args.query}" if args.query else "")
    print(f"dashboard: {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
