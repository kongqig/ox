"""server — HTTP/HTTPS/WebSocket server with a tiny router.

    serve 8080 {
      get "/hello/:name" { res.json({msg: "hi " + req.params.name}) }
      post "/echo"       { res.json(req.json) }
      static "/assets" "./public"
      ws "/chat"         { conn.on("message", fn (m) { conn.send(m) }) }
    }

Options: host (default 127.0.0.1), daemon=true, tls={cert, key},
debug=true (500s include the error text).
"""
import asyncio
import base64
import hashlib
import json as _json
import mimetypes
import os
import ssl as _ssl
import struct
import urllib.parse

from .. import tty
from ..errors import OxThrow
from ..values import NativeModule, OxErrorValue, builtin, ox_str
from . import logmod

MAX_HEADER = 64 * 1024
MAX_BODY = 32 * 1024 * 1024
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Res:
    """Response builder; ox handlers call res.json(...) etc."""

    def __init__(self):
        self.status_code = 200
        self.headers = {"Content-Type": "text/plain; charset=utf-8"}
        self.body = b""
        self._done = False

    def status(self, code):
        self.status_code = int(code)
        return self

    def set_header(self, name, value):
        self.headers[ox_str(name)] = ox_str(value)
        return self

    def send(self, body="", status=None, headers=None):
        if status is not None:
            self.status_code = int(status)
        if headers:
            for k, v in headers.items():
                self.headers[ox_str(k)] = ox_str(v)
        self.body = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        self.headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        self._done = True
        return self

    def json(self, obj, status=None):
        if status is not None:
            self.status_code = int(status)
        self.body = _json.dumps(obj, ensure_ascii=False,
                                default=ox_str).encode("utf-8")
        self.headers["Content-Type"] = "application/json; charset=utf-8"
        self._done = True
        return self

    def html(self, body, status=None):
        if status is not None:
            self.status_code = int(status)
        self.body = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        self.headers["Content-Type"] = "text/html; charset=utf-8"
        self._done = True
        return self

    def text(self, body, status=None):
        return self.send(body, status=status)

    def redirect(self, url, status=302):
        self.status_code = int(status)
        self.headers["Location"] = ox_str(url)
        self.body = b""
        self._done = True
        return self

    def file(self, path, download=None, root=None):
        """Serve a file from disk.

        `root` (optional) constrains the path: anything resolving outside it
        is rejected with 403 — use it whenever `path` is derived from user
        input (e.g. req.params / req.query) to prevent path traversal.
        Without `root`, arbitrary paths are allowed (trusted, script-chosen
        paths only).
        """
        path = ox_str(path)
        if root is not None:
            root = os.path.realpath(ox_str(root))
            real = os.path.realpath(path)
            if real != root and not real.startswith(root + os.sep):
                return self.send("forbidden", status=403)
        if not os.path.isfile(path):
            return self.send("not found", status=404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            self.body = f.read(MAX_BODY)
        self.headers["Content-Type"] = ctype
        if download:
            self.headers["Content-Disposition"] = \
                'attachment; filename="%s"' % ox_str(download)
        self._done = True
        return self


_STATUS_TEXT = {200: "OK", 201: "Created", 204: "No Content", 301: "Moved",
                302: "Found", 304: "Not Modified", 400: "Bad Request",
                401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                405: "Method Not Allowed", 409: "Conflict", 413: "Too Large",
                500: "Internal Server Error", 501: "Not Implemented"}


class WsConn:
    """Server-side websocket connection (frames to clients are unmasked)."""

    def __init__(self, reader, writer, ip, interp=None):
        self.reader = reader
        self.writer = writer
        self.ip = ip
        self.interp = interp
        self.handlers = {}
        self.closed = False
        self.id = "ws-" + base64.b64encode(os.urandom(5)).decode("ascii")

    async def send(self, text):
        if self.closed:
            return False
        await self._frame(0x1, ox_str(text).encode("utf-8"))
        return True

    async def send_json(self, obj):
        return await self.send(_json.dumps(obj, ensure_ascii=False,
                                           default=ox_str))

    async def _frame(self, opcode, payload):
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([n])
        elif n < 65536:
            header += bytes([126]) + struct.pack(">H", n)
        else:
            header += bytes([127]) + struct.pack(">Q", n)
        self.writer.write(header + payload)
        await self.writer.drain()

    async def _read_frame(self):
        head = await self.reader.readexactly(2)
        opcode = head[0] & 0x0F
        fin = bool(head[0] & 0x80)
        masked = bool(head[1] & 0x80)
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await self.reader.readexactly(8))[0]
        if n > MAX_BODY:
            raise ConnectionResetError("frame too large")
        mask = await self.reader.readexactly(4) if masked else None
        payload = await self.reader.readexactly(n) if n else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    async def _close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self._frame(0x8, b"")
        except (OSError, ConnectionResetError):
            pass
        self.writer.close()

    async def close(self):
        await self._close()

    def on(self, event, fn):
        self.handlers[event] = fn
        return True

    async def _fire(self, event, arg=None):
        from ..values import call_value
        fn = self.handlers.get(event)
        if fn is None:
            return
        try:
            await call_value(self.interp, fn, [arg] if arg is not None else [])
        except Exception as e:  # noqa: BLE001 — handlers must not kill sockets
            logmod.log_error("ws handler '%s' failed: %s" % (event, e))

    async def run(self):
        """Frame loop; dispatches to registered handlers."""
        try:
            await self._fire("connect", self)
            chunks = []
            msg_op = None
            while not self.closed:
                fin, op, payload = await self._read_frame()
                if op == 0x8:
                    break
                if op == 0x9:
                    await self._frame(0xA, payload)
                    continue
                if op == 0xA:
                    continue
                if msg_op is None:
                    msg_op = op
                chunks.append(payload)
                if fin:
                    data = b"".join(chunks)
                    chunks = []
                    msg_op = None
                    text = data.decode("utf-8", errors="replace")
                    await self._fire("message", text)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError,
                asyncio.CancelledError):
            pass
        finally:
            await self._close()
            await self._fire("close", self)

    def __repr__(self):
        return "<ws conn %s>" % self.id


class ServerHandle:
    def __init__(self, server, host, port, tls):
        self.server = server
        self.host = host
        self.port = port
        self.tls = tls
        if port == 0 and server.sockets:
            self.port = server.sockets[0].getsockname()[1]

    @property
    def url(self):
        return "%s://%s:%s" % ("https" if self.tls else "http",
                               self.host, self.port)

    def stop(self):
        self.server.close()

    async def wait(self):
        async with self.server:
            await self.server.serve_forever()

    def __repr__(self):
        return "<server %s>" % self.url


def _segments(path):
    return [s for s in path.split("/") if s]


class Router:
    def __init__(self):
        self.routes = []    # (method, segments, handler)
        self.statics = []   # (prefix, dir)
        self.ws_routes = []  # (segments, handler)

    def match(self, method, path):
        segs = _segments(path)
        allowed = set()
        for m, rsegs, handler in self.routes:
            params = _match_segs(rsegs, segs)
            if params is not None:
                if m == method or (method == "HEAD" and m == "GET"):
                    return handler, params
                allowed.add(m)
        for rsegs, handler in self.ws_routes:
            if _match_segs(rsegs, segs) is not None:
                allowed.add("GET(ws)")
        if allowed:
            return None, "405:%s" % ",".join(sorted(allowed))
        return None, "404"

    def match_ws(self, path):
        segs = _segments(path)
        for rsegs, handler in self.ws_routes:
            params = _match_segs(rsegs, segs)
            if params is not None:
                return handler, params
        return None, None

    def match_static(self, path):
        segs = _segments(path)
        for prefix, directory in self.statics:
            psegs = _segments(prefix)
            if segs[:len(psegs)] == psegs:
                rel = "/".join(s for s in segs[len(psegs):] if s not in ("", "."))
                root = os.path.realpath(directory)
                fpath = os.path.realpath(os.path.join(root, rel))
                if not (fpath == root or fpath.startswith(root + os.sep)):
                    return None, None  # path traversal blocked
                if not rel:
                    return None, None
                return root, fpath
        return None, None


def _match_segs(rsegs, segs):
    if len(rsegs) != len(segs):
        return None
    params = {}
    for r, s in zip(rsegs, segs):
        if r.startswith(":") and len(r) > 1:
            params[r[1:]] = urllib.parse.unquote(s)
        elif r != s:
            return None
    return params


async def serve(interp, port, options, router, env=None):
    """Collect routes by running the router body, then start the server."""
    router_obj = Router()
    entries = []
    interp.route_collectors.append(entries)
    try:
        if callable(router) and not hasattr(router, "stmts"):
            r = router()
            if asyncio.iscoroutine(r):
                await r
        else:
            from ..environment import Env
            from .. import ast_nodes as A
            if isinstance(router, A.Block):
                await interp.exec_block(router, Env(env) if env else interp.globals)
            else:
                r = router()
                if asyncio.iscoroutine(r):
                    await r
    finally:
        interp.route_collectors.pop()
    for entry in entries:
        kind = entry[0]
        if kind == "route":
            _, method, path, handler = entry
            router_obj.routes.append((method, _segments(path), handler))
        elif kind == "static":
            _, prefix, directory = entry
            router_obj.statics.append((prefix, directory))
        elif kind == "ws":
            _, path, handler = entry
            router_obj.ws_routes.append((_segments(path), handler))

    options = options or {}
    host = ox_str(options.get("host", "127.0.0.1"))
    daemon = bool(options.get("daemon", False))
    debug = bool(options.get("debug", False)) or \
        os.environ.get("OX_DEBUG", "") != ""
    tls_opts = options.get("tls")
    ssl_ctx = None
    if tls_opts:
        if not isinstance(tls_opts, dict) or not tls_opts.get("cert"):
            raise OxThrow(OxErrorValue(
                "serve tls= expects {cert: \"cert.pem\", key: \"key.pem\"} "
                "— got %s" % ox_str(tls_opts)))
        try:
            ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(ox_str(tls_opts["cert"]),
                                    ox_str(tls_opts.get("key")))
        except (OSError, ValueError, _ssl.SSLError) as e:
            raise OxThrow(OxErrorValue(
                "serve tls= cannot load certificate: %s — check that the "
                "cert/key paths exist and match" % e))

    async def handle(reader, writer):
        try:
            await _handle_conn(interp, router_obj, reader, writer, debug)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    server = await asyncio.start_server(handle, host, int(port), ssl=ssl_ctx)
    handle_obj = ServerHandle(server, host, int(port), tls=bool(ssl_ctx))

    if daemon:
        return handle_obj

    scheme = "https" if ssl_ctx else "http"
    print(tty.bold("▶ ox server listening on %s://%s:%s" % (scheme, host,
                                                            int(port))))
    for m, rsegs, _h in router_obj.routes:
        print("  " + tty.cyan("%-6s" % m) + " /" + "/".join(rsegs))
    for rsegs, _h in router_obj.ws_routes:
        print("  " + tty.magenta("%-6s" % "ws") + " /" + "/".join(rsegs))
    for prefix, directory in router_obj.statics:
        print("  " + tty.gray("%-6s" % "static") + " %s -> %s" % (prefix,
                                                                   directory))
    print(tty.gray("  (Ctrl+C to stop)"))
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        print(tty.yellow("\n■ server stopped"))
        return handle_obj
    return handle_obj


async def _handle_conn(interp, router, reader, writer, debug):
    ip = writer.get_extra_info("peername")[0] if \
        writer.get_extra_info("peername") else "?"
    keep = True
    while keep:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),
                                          timeout=75)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError):
            return
        if len(head) > MAX_HEADER:
            _write_simple(writer, 413, "headers too large")
            return
        try:
            lines = head.decode("latin1").split("\r\n")
            method, raw_path, _proto = lines[0].split(" ", 2)
        except ValueError:
            _write_simple(writer, 400, "malformed request line")
            return
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        body = b""
        clen = headers.get("content-length")
        if clen and method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                n = int(clen)
            except ValueError:
                _write_simple(writer, 400, "bad content-length")
                return
            if n > MAX_BODY:
                # Drain (bounded) before replying so well-behaved clients
                # can still read the 413 instead of hitting a connection
                # reset mid-upload.
                remaining = n
                drained = 0
                try:
                    while remaining > 0 and drained <= 2 * MAX_BODY:
                        chunk = await asyncio.wait_for(
                            reader.read(min(remaining, 1 << 20)), timeout=10)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        drained += len(chunk)
                except (asyncio.TimeoutError, OSError):
                    pass
                _write_simple(writer, 413, "body too large")
                return
            body = await reader.readexactly(n) if n else b""

        # websocket upgrade?
        if headers.get("upgrade", "").lower() == "websocket":
            handler, _params = router.match_ws(raw_path.split("?")[0])
            if handler is None:
                _write_simple(writer, 404, "no websocket at this path")
                return
            await _ws_upgrade(interp, handler, reader, writer, headers, ip)
            return  # ws connections own the socket until close

        await _dispatch(interp, router, writer, method, raw_path, headers,
                        body, ip, debug)
        conn_hdr = headers.get("connection", "").lower()
        keep = conn_hdr != "close" and "close" not in conn_hdr


async def _dispatch(interp, router, writer, method, raw_path, headers, body,
                    ip, debug):
    parts = urllib.parse.urlsplit(raw_path)
    path = urllib.parse.unquote(parts.path)
    query = {}
    for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        query[k] = v
    text_body = body.decode("utf-8", errors="replace")
    req = {"method": method.upper(), "path": path, "raw_path": raw_path,
           "query": query, "headers": headers, "body": text_body,
           "params": {}, "ip": ip, "json": None, "form": None}
    ctype = headers.get("content-type", "")
    if "json" in ctype and text_body:
        try:
            req["json"] = _json.loads(text_body)
        except ValueError:
            req["json"] = None
    elif "urlencoded" in ctype and text_body:
        req["form"] = {k: v for k, v in
                       urllib.parse.parse_qsl(text_body,
                                              keep_blank_values=True)}

    handler, outcome = router.match(method.upper(), path)
    res = Res()
    if handler is None and method.upper() == "GET":
        # static file routes (with path-traversal protection)
        root, fpath = router.match_static(path)
        if fpath is not None:
            res.file(fpath)
            _write_res(writer, res)
            return
    if handler is None:
        if isinstance(outcome, str) and outcome.startswith("405"):
            res.json({"error": "method not allowed",
                      "allowed": outcome[4:].split(",")}, status=405)
            res.headers["Allow"] = outcome[4:]
        else:
            res.json({"error": "not found", "path": path}, status=404)
    else:
        handler, params = handler, outcome
        if isinstance(params, dict):
            req["params"] = params
        try:
            r = handler(req, res)
            if asyncio.iscoroutine(r):
                await r
        except Exception as e:  # noqa: BLE001 — handler errors become 500s
            from ..values import to_ox_error
            err = to_ox_error(e)
            logmod.log_error("%s %s -> 500 (%s)" % (method, path, err.msg))
            payload = {"error": "internal server error", "path": path}
            if debug:
                payload["detail"] = err.msg
                payload["trace"] = [str(f) for f in err.trace]
            res.json(payload, status=500)
        if not res._done:
            res.send("")
    _write_res(writer, res)


def _write_res(writer, res):
    reason = _STATUS_TEXT.get(res.status_code, "OK")
    body = res.body if body_fits(res.body) else res.body[:MAX_BODY]
    head = "HTTP/1.1 %d %s\r\n" % (res.status_code, reason)
    hdrs = dict(res.headers)
    hdrs.setdefault("Content-Length", str(len(body)))
    hdrs.setdefault("Server", "ox")
    for k, v in hdrs.items():
        # header injection guard: strip CR/LF from user-controlled keys/values
        k = str(k).replace("\r", " ").replace("\n", " ")
        v = str(v).replace("\r", " ").replace("\n", " ")
        head += "%s: %s\r\n" % (k, v)
    head += "\r\n"
    writer.write(head.encode("latin1", errors="replace") + body)


def body_fits(b):
    return len(b) <= MAX_BODY


def _write_simple(writer, status, text):
    res = Res()
    res.send(text, status=status)
    try:
        _write_res(writer, res)
    except OSError:
        pass


async def _ws_upgrade(interp, handler, reader, writer, headers, ip):
    key = headers.get("sec-websocket-key")
    if not key:
        _write_simple(writer, 400, "missing sec-websocket-key")
        return
    accept = base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
    resp = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % accept)
    writer.write(resp.encode("ascii"))
    await writer.drain()
    conn = WsConn(reader, writer, ip, interp=interp)
    try:
        r = handler(conn)
        if asyncio.iscoroutine(r):
            await r
    except Exception as e:  # noqa: BLE001
        logmod.log_error("ws route handler failed: %s" % e)
    await conn.run()


def build():
    return NativeModule("server", {
        "stop": builtin("stop")(_not_running),
        "note": builtin("note")(lambda: "use serve to start a server"),
    })


def _not_running():
    raise OxThrow(OxErrorValue(
        "no server running in this context — use `serve <port> { ... }`"))
