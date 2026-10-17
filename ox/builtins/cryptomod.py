"""crypto — hashes, base64, uuids, url encoding."""
import base64
import hashlib
import hmac as _hmac
import secrets
import string
import urllib.parse as _url

from ..values import NativeModule, builtin, ox_str

_ALGOS = ("md5", "sha1", "sha256", "sha512")


def _hash(algo, data):
    data = _as_bytes(data)
    if algo not in _ALGOS:
        raise ValueError("unknown hash algo '%s' (use %s)" %
                         (algo, "/".join(_ALGOS)))
    return hashlib.new(algo, data).hexdigest()


def _as_bytes(data):
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, bytes):
        return data
    return ox_str(data).encode("utf-8")


def _hmac_sha256(key, msg):
    return _hmac.new(_as_bytes(key), _as_bytes(msg), hashlib.sha256).hexdigest()


def _hash_file(path, algo="sha256"):
    if algo not in _ALGOS:
        raise ValueError("unknown hash algo '%s'" % algo)
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _uuid():
    import uuid
    return str(uuid.uuid4())


def _b64_encode(data):
    return base64.b64encode(_as_bytes(data)).decode("ascii")


def _b64_decode(data):
    return base64.b64decode(ox_str(data)).decode("utf-8", errors="replace")


def _url_encode(s):
    return _url.quote(ox_str(s), safe="")


def _url_decode(s):
    return _url.unquote(ox_str(s))


def _random_id(n=8):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(int(n)))


def build():
    return NativeModule("crypto", {
        "md5": builtin("md5")(lambda data: _hash("md5", data)),
        "sha1": builtin("sha1")(lambda data: _hash("sha1", data)),
        "sha256": builtin("sha256")(lambda data: _hash("sha256", data)),
        "sha512": builtin("sha512")(lambda data: _hash("sha512", data)),
        "hash": builtin("hash")(_hash),
        "hash_file": builtin("hash_file")(_hash_file),
        "hmac_sha256": builtin("hmac_sha256")(_hmac_sha256),
        "uuid": builtin("uuid")(_uuid),
        "b64_encode": builtin("b64_encode")(_b64_encode),
        "b64_decode": builtin("b64_decode")(_b64_decode),
        "url_encode": builtin("url_encode")(_url_encode),
        "url_decode": builtin("url_decode")(_url_decode),
        "random_id": builtin("random_id")(_random_id),
    })
