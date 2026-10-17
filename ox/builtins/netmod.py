"""net — HTTP client (get/post/put/patch/delete/head), downloads, websocket
client, and URL utilities. Built on urllib (no third-party dependencies),
executed in worker threads so requests from concurrent `spawn`s overlap.
"""
import asyncio
import base64
import json as _json
import os
import socket
import ssl as _ssl
import struct
import time as _time
import urllib.error
import urllib.parse
import urllib.request

from ..values import NativeModule, builtin, ox_str

MAX_BODY = 64 * 1024 * 1024


def _headers_dict(headers):
    out = {}
    if headers:
        for k, v in headers.items():
            out[ox_str(k)] = ox_str(v)
    return out


def _apply_query(url, query):
    if not query:
        return url
    parts = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    for k, v in query.items():
        qs.append((ox_str(k), ox_str(v)))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urllib.parse.urlencode(qs), parts.fragment))


def _ssl_context(verify=True):
    if verify:
        return _ssl.create_default_context()
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    return ctx


def _do_request(method, url, headers=None, query=None, timeout=30,
                data=None, json=None, form=None, follow=True, verify=True):
    """Blocking worker; returns an ox response dict."""
    url = _apply_query(url, query)
    body = None
    hdrs = _headers_dict(headers)
    if json is not None:
        body = _json.dumps(json, ensure_ascii=False,
                           default=ox_str).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(
            {ox_str(k): ox_str(v) for k, v in form.items()}).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in hdrs.items():
        req.add_header(k, v)
    ctx = _ssl_context(verify) if url.lower().startswith("https") else None
    try:
        resp = urllib.request.urlopen(req, timeout=float(timeout), context=ctx)
        raw = resp.read(MAX_BODY)
        return _resp_ok(resp.status, resp.headers, raw, url)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(MAX_BODY)
        except Exception:  # noqa: BLE001
            raw = b""
        return _resp_ok(e.code, e.headers, raw, url)
    except urllib.error.URLError as e:
        reason = e.reason
        return {"ok": False, "status": 0, "reason": str(reason), "headers": {},
                "body": "", "json": None, "url": url,
                "error": str(reason)}
    except (OSError, socket.timeout) as e:
        return {"ok": False, "status": 0, "reason": str(e), "headers": {},
                "body": "", "json": None, "url": url, "error": str(e)}


def _resp_ok(status, headers, raw, url):
    body = raw.decode("utf-8", errors="replace")
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    parsed_json = None
    ctype = hdrs.get("content-type", "")
    if "json" in ctype:
        try:
            parsed_json = _json.loads(body)
        except ValueError:
            parsed_json = None
    return {"ok": 200 <= int(status) < 300, "status": int(status),
            "reason": "", "headers": hdrs, "body": body, "json": parsed_json,
            "url": url}


async def get(url, headers=None, query=None, timeout=30, follow=True,
              verify=True):
    return await asyncio.to_thread(_do_request, "GET", url, headers, query,
                                   timeout, None, None, None, follow, verify)


async def post(url, data=None, json=None, form=None, headers=None, query=None,
               timeout=30, verify=True):
    return await asyncio.to_thread(_do_request, "POST", url, headers, query,
                                   timeout, data, json, form, True, verify)


async def put(url, data=None, json=None, form=None, headers=None, query=None,
              timeout=30, verify=True):
    return await asyncio.to_thread(_do_request, "PUT", url, headers, query,
                                   timeout, data, json, form, True, verify)


async def patch(url, data=None, json=None, form=None, headers=None, query=None,
                timeout=30, verify=True):
    return await asyncio.to_thread(_do_request, "PATCH", url, headers, query,
                                   timeout, data, json, form, True, verify)


async def delete(url, headers=None, query=None, timeout=30, verify=True):
    return await asyncio.to_thread(_do_request, "DELETE", url, headers, query,
                                   timeout, None, None, None, True, verify)


async def head(url, headers=None, query=None, timeout=30, verify=True):
    return await asyncio.to_thread(_do_request, "HEAD", url, headers, query,
                                   timeout, None, None, None, True, verify)


async def download(url, to, headers=None, timeout=60, verify=True):
    def work():
        req = urllib.request.Request(url)
        for k, v in _headers_dict(headers).items():
            req.add_header(k, v)
        ctx = _ssl_context(verify) if url.lower().startswith("https") else None
        try:
            resp = urllib.request.urlopen(req, timeout=float(timeout), context=ctx)
            with open(to, "wb") as f:
                size = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
            return {"ok": True, "status": resp.status, "path": to, "size": size}
        except urllib.error.HTTPError as e:
            return {"ok": False, "status": e.code, "path": to, "size": 0,
                    "error": "HTTP %s" % e.code}
        except (OSError, urllib.error.URLError) as e:
            return {"ok": False, "status": 0, "path": to, "size": 0,
                    "error": str(e)}

    return await asyncio.to_thread(work)


async def tcp_ping(host, port=80, timeout=2):
    def work():
        t0 = _time.monotonic()
        try:
            with socket.create_connection((host, int(port)), timeout=float(timeout)):
                return {"ok": True, "ms": round((_time.monotonic() - t0) * 1000, 2)}
        except OSError as e:
            return {"ok": False, "ms": None, "error": str(e)}

    return await asyncio.to_thread(work)


async def wait_port(host, port, timeout=10, interval=0.1):
    """Poll until a TCP port accepts connections; true on success, false on
    timeout. The natural companion to os.start() when waiting for a service."""
    host = ox_str(host)
    port = int(port)
    deadline = _time.monotonic() + float(timeout)

    def try_connect():
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    while True:
        if await asyncio.to_thread(try_connect):
            return True
        if _time.monotonic() >= deadline:
            return False
        await asyncio.sleep(float(interval))


def parse_url(url):
    parts = urllib.parse.urlsplit(url)
    query = {}
    for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        query[k] = v
    return {"scheme": parts.scheme or "http", "host": parts.hostname or "",
            "port": parts.port or (443 if parts.scheme == "https" else 80),
            "path": parts.path or "/", "query": query,
            "fragment": parts.fragment, "user": parts.username,
            "password": parts.password}


def url_encode(s):
    return urllib.parse.quote(ox_str(s), safe="")


def url_decode(s):
    return urllib.parse.unquote(ox_str(s))


# ---------------------------------------------------------------------------
# websocket client (RFC 6455 over asyncio streams)
# ---------------------------------------------------------------------------

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WsClient:
    def __init__(self, reader, writer, url, interp=None, pending=b""):
        self.reader = reader
        self.writer = writer
        self.url = url
        self.interp = interp
        self.handlers = {}
        self.queue = None
        self.reader_task = None
        self.closed = False
        self.id = "ws-" + base64.b64encode(os.urandom(5)).decode("ascii")
        # bytes that arrived together with the handshake response
        self._buf = bytes(pending)
        self._pos = 0

    async def _read_exact(self, n):
        while (len(self._buf) - self._pos) < n:
            chunk = await self.reader.read(4096)
            if not chunk:
                raise asyncio.IncompleteReadError(self._buf[self._pos:], n)
            self._buf = self._buf[self._pos:] + chunk
            self._pos = 0
        out = self._buf[self._pos:self._pos + n]
        self._pos += n
        if self._pos > 65536:
            self._buf = self._buf[self._pos:]
            self._pos = 0
        return out

    # ---- outgoing frames (client frames are masked) ----
    async def send(self, text):
        if self.closed:
            raise RuntimeError("websocket is closed")
        await self._send_frame(0x1, ox_str(text).encode("utf-8"))

    async def send_json(self, obj):
        await self.send(_json.dumps(obj, ensure_ascii=False, default=ox_str))

    async def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.writer.write(header + mask + masked)
        await self.writer.drain()

    # ---- incoming frames ----
    async def _read_frame(self):
        head = await self._read_exact(2)
        opcode = head[0] & 0x0F
        fin = bool(head[0] & 0x80)
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await self._read_exact(8))[0]
        if n > MAX_BODY:
            raise RuntimeError("websocket frame too large")
        payload = await self._read_exact(n) if n else b""
        return fin, opcode, payload

    async def _read_message(self):
        """Returns (opcode, bytes) for a full (defragmented) message."""
        chunks = []
        opcode = None
        while True:
            fin, op, payload = await self._read_frame()
            if op == 0x8:  # close
                return 0x8, payload
            if op == 0x9:  # ping -> pong
                await self._send_frame(0xA, payload)
                continue
            if op == 0xA:  # pong
                continue
            if opcode is None:
                opcode = op
            chunks.append(payload)
            if fin:
                return opcode, b"".join(chunks)

    async def recv(self, timeout=None):
        """Next text message, or null on timeout/close."""
        if self.closed:
            return None
        try:
            if timeout is None:
                op, payload = await self._read_message()
            else:
                op, payload = await asyncio.wait_for(self._read_message(),
                                                     timeout=float(timeout))
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionResetError, OSError):
            return None
        if op == 0x8:
            await self._close_handshake()
            return None
        if op == 0x2:
            return payload.decode("utf-8", errors="replace")
        return payload.decode("utf-8", errors="replace")

    async def _close_handshake(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self._send_frame(0x8, b"")
        except (OSError, RuntimeError):
            pass
        self.writer.close()

    async def close(self):
        if self.reader_task:
            self.reader_task.cancel()
        await self._close_handshake()

    def on(self, event, fn):
        self.handlers[event] = fn
        if self.reader_task is None:
            self.queue = asyncio.Queue()
            self.reader_task = asyncio.get_running_loop()\
                .create_task(self._background_read())
        return True

    async def _fire(self, event, arg=None):
        from ..values import call_value
        fn = self.handlers.get(event)
        if fn is None:
            return
        try:
            await call_value(self.interp, fn, [arg] if arg is not None else [])
        except Exception as e:  # noqa: BLE001 — handlers must not kill sockets
            import sys
            print("ws client handler '%s' failed: %s" % (event, e),
                  file=sys.stderr)

    async def _background_read(self):
        try:
            while not self.closed:
                op, payload = await self._read_message()
                if op == 0x8:
                    break
                text = payload.decode("utf-8", errors="replace")
                await self._fire("message", text)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError,
                asyncio.CancelledError):
            pass
        finally:
            self.closed = True
            await self._fire("close", True)

    def __repr__(self):
        return "<ws client %s>" % self.url


async def ws(interp, url, headers=None, timeout=10, verify=True):
    """Open a websocket connection; returns a WsClient.

    verify=false accepts self-signed certificates (wss:// only).
    """
    parts = urllib.parse.urlsplit(url)
    secure = parts.scheme == "wss"
    host = parts.hostname
    port = parts.port or (443 if secure else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port,
                                ssl=_ssl_context(verify) if secure
                                else None),
        timeout=float(timeout))

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
           "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
           "Sec-WebSocket-Version: 13\r\n" % (path, host, key))
    for k, v in _headers_dict(headers).items():
        req += "%s: %s\r\n" % (k, v)
    req += "\r\n"
    writer.write(req.encode("utf-8"))
    await writer.drain()

    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = await reader.read(4096)
        if not chunk:
            raise RuntimeError("websocket handshake failed: connection closed")
        resp += chunk
        if len(resp) > 65536:
            raise RuntimeError("websocket handshake response too large")
    status_line = resp.split(b"\r\n", 1)[0].decode("latin1")
    if "101" not in status_line:
        writer.close()
        raise RuntimeError("websocket handshake failed: %s" % status_line)
    leftover = resp.split(b"\r\n\r\n", 1)[1]
    return WsClient(reader, writer, url, interp=interp, pending=leftover)


def build():
    return NativeModule("net", {
        "get": builtin("get")(get),
        "post": builtin("post")(post),
        "put": builtin("put")(put),
        "patch": builtin("patch")(patch),
        "delete": builtin("delete")(delete),
        "head": builtin("head")(head),
        "request": builtin("request")(_do_request),
        "download": builtin("download")(download),
        "tcp_ping": builtin("tcp_ping")(tcp_ping),
        "wait_port": builtin("wait_port")(wait_port),
        "ws": builtin("ws", needs_interp=True)(ws),
        "parse_url": builtin("parse_url")(parse_url),
        "url_encode": builtin("url_encode")(url_encode),
        "url_decode": builtin("url_decode")(url_decode),
    })


def build_http_alias():
    return NativeModule("http", {
        "get": builtin("get")(get),
        "post": builtin("post")(post),
        "put": builtin("put")(put),
        "patch": builtin("patch")(patch),
        "delete": builtin("delete")(delete),
        "head": builtin("head")(head),
        "download": builtin("download")(download),
    })
