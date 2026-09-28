"""The local xforge server.

Standard library only. A design tool that needs a web framework installed
before it will start is a tool that stops working on the machine where you
need it most, so this uses http.server and pays the small cost of routing
by hand.

Binds to 127.0.0.1 by default. This serves a project's design files and
talks to a supplier on the user's behalf; neither belongs on a public
interface.
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).parent / "static"

# Reference designators as they appear in finding text: letters then digits.
_REFDES = re.compile(r"([A-Z]{1,3}[0-9]{1,4})")


@dataclass
class AppState:
    """What the running server knows about the project it was pointed at."""

    project: Path
    netlist: Path | None = None
    config: Path | None = None
    model: Path | None = None
    started: float = 0.0


class ApiError(Exception):
    """An error with an HTTP status and a message meant for a human."""

    def __init__(self, message: str, status: int = 400, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.hint = hint


Route = Callable[["Handler", dict[str, list[str]], dict[str, Any] | None], Any]
_ROUTES: dict[tuple[str, str], Route] = {}


def route(method: str, path: str):
    def wrap(func: Route) -> Route:
        _ROUTES[(method, path)] = func
        return func

    return wrap


# ── API ───────────────────────────────────────────────────────────────


@route("GET", "/api/status")
def _status(h: "Handler", q, body):
    from xforge import __version__
    from xforge.ui.parts import Library

    lib = Library(h.state.project)
    vendored = lib.load()
    return {
        "version": __version__,
        "project": str(h.state.project),
        "netlist": str(h.state.netlist) if h.state.netlist else None,
        "model": str(h.state.model) if h.state.model else None,
        "vendored": len(vendored),
        "parts": sorted(vendored),
    }


@route("GET", "/api/parts/search")
def _search(h: "Handler", q, body):
    from xforge.ui import parts

    keyword = (q.get("q") or [""])[0]
    page = int((q.get("page") or ["1"])[0])
    total, found = parts.search(keyword, page=page)
    lib = parts.Library(h.state.project).load()
    return {
        "query": keyword,
        "total": total,
        "page": page,
        "results": [
            {**p.to_dict(), "vendored": p.lcsc.upper() in lib} for p in found
        ],
    }


@route("POST", "/api/parts/import")
def _import(h: "Handler", q, body):
    from xforge.ui.parts import Library

    lcsc = ((body or {}).get("lcsc") or "").strip()
    if not lcsc:
        raise ApiError("No part id given", 400)
    record = Library(h.state.project).vendor(lcsc)
    return {"imported": record.to_dict()}


def _viewer():
    """The STEP reader, imported late so the viewer stays an optional extra."""
    try:
        import xforge.viewer as viewer
    except ImportError as exc:
        raise ApiError(
            "The board viewer is not installed",
            501,
            'Install it with: pip install -e ".[viewer]"',
        ) from exc
    return viewer


def _target(h: "Handler", q) -> Path:
    """The model to act on: an explicit path, else the one we were started with."""
    path = (q.get("path") or [None])[0]
    target = Path(path) if path else h.state.model
    if not target:
        raise ApiError(
            "No board loaded",
            404,
            "Start the server with --model pointing at a STEP file.",
        )
    if not target.exists():
        raise ApiError(f"{target.name} does not exist", 404)
    return target


@route("GET", "/api/model/info")
def _model_info(h: "Handler", q, body):
    target = _target(h, q)
    return {"path": str(target), **_viewer().info(target)}


@route("GET", "/api/model/glb")
def _model_glb(h: "Handler", q, body):
    target = _target(h, q)
    result = _viewer().convert(target)
    h.send_file(result.glb, "model/gltf-binary")
    return None  # send_file already wrote the response


@route("GET", "/api/board")
def _board(h: "Handler", q, body):
    """The board as polygons the viewer extrudes client side.

    Sending geometry rather than a mesh keeps the payload small and keeps
    every solid addressable by reference designator - which is what lets a
    design-rule finding point at a part.
    """
    from xforge.viewer import read_board, to_scene

    target = _target(h, q)
    if target.suffix.lower() not in (".emn", ".idf"):
        raise ApiError(
            f"{target.name} is not an IDF board file",
            400,
            "Point --model at the .emn your ECAD tool exports, with its "
            ".emp beside it.",
        )
    # Refdes named by findings, so the viewport can show what the rules found.
    highlight = set()
    if h.state.netlist:
        try:
            from xforge import readers
            from xforge.config import Config
            from xforge.rules import Status, run

            design = readers.read(h.state.netlist)
            for f in run(design, Config.load(h.state.config)):
                if f.status is not Status.VIOLATION:
                    continue
                for s in [f.summary, *f.subjects]:
                    highlight.update(_REFDES.findall(str(s)))
        except Exception:
            # A viewer that refuses to draw because the rules failed is
            # worse than a viewer with nothing highlighted.
            pass
    return to_scene(read_board(target), highlight=highlight)


@route("GET", "/api/check")
def _check(h: "Handler", q, body):
    from xforge import readers
    from xforge.config import Config
    from xforge.rules import run

    if not h.state.netlist:
        raise ApiError(
            "No netlist loaded",
            404,
            "Start the server with --netlist pointing at a .net file.",
        )
    design = readers.read(h.state.netlist)
    config = Config.load(h.state.config)
    findings = run(design, config)
    return {
        "design": design.name,
        "census": design.census(),
        "findings": [
            {
                "rule": f.rule_id,
                "severity": f.severity.label,
                "status": f.status.value,
                "summary": f.summary,
                "detail": f.detail,
                "subjects": f.subjects,
            }
            for f in findings
        ],
    }


# ── plumbing ──────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = "xforge"
    sys_version = ""
    state: AppState  # set on the server, exposed here for convenience

    def log_message(self, fmt, *args):  # noqa: D102 - quieten the default log
        pass

    # -- responses

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, exc: ApiError) -> None:
        self.send_json(
            {"error": exc.message, "hint": exc.hint}, status=exc.status
        )

    # -- routing

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    self.send_error_json(ApiError("Request body is not JSON", 400))
                    return

        handler = _ROUTES.get((method, path))
        if handler is not None:
            try:
                result = handler(self, query, body)
            except ApiError as exc:
                self.send_error_json(exc)
            except Exception as exc:  # surfaced, not swallowed
                traceback.print_exc()
                self.send_error_json(
                    ApiError(f"{type(exc).__name__}: {exc}", 500)
                )
            else:
                if result is not None:
                    self.send_json(result)
            return

        if method == "GET":
            self._serve_static(path)
            return
        self.send_error_json(ApiError(f"No route for {method} {path}", 404))

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC / name).resolve()
        # Refuse anything that escapes the static directory.
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            self.send_error_json(ApiError(f"Not found: {path}", 404))
            return
        self.send_file(target)

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")


def serve(
    project: Path,
    netlist: Path | None = None,
    config: Path | None = None,
    model: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 7800,
    open_browser: bool = True,
) -> None:
    """Run the UI until interrupted."""
    state = AppState(project=Path(project), netlist=netlist, config=config, model=model)

    class Bound(Handler):
        pass

    Bound.state = state

    httpd = ThreadingHTTPServer((host, port), Bound)
    url = f"http://{host}:{port}/"
    print(f"xforge ui  {url}")
    print(f"  project  {state.project}")
    print(f"  netlist  {state.netlist or '-'}")
    print(f"  model    {state.model or '-'}")
    print("  ctrl-c to stop")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
