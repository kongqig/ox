"""data — JSON / CSV / YAML / TOML plus a lightweight schema validator."""
import csv
import io
import json as _json
import re
from datetime import datetime

from ..values import (BoundMethod, BuiltinFunction, NativeModule,
                       OxFunction, builtin, ox_repr, ox_str, truthy,
                       type_name)

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None

try:
    import tomllib as _tomllib
except ImportError:  # pragma: no cover
    _tomllib = None


# ---- json -------------------------------------------------------------------

def json_parse(s):
    try:
        return _json.loads(s)
    except _json.JSONDecodeError as e:
        raise ValueError("invalid JSON: %s" % e)


def json_dump(v, pretty=False):
    try:
        return _json.dumps(v, indent=2 if pretty else None,
                           ensure_ascii=False, default=ox_str)
    except (TypeError, ValueError) as e:
        raise ValueError("cannot serialize to JSON: %s" % e)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        try:
            return _json.load(f)
        except _json.JSONDecodeError as e:
            raise ValueError("invalid JSON in %s: %s" % (path, e))


def write_json(path, v, pretty=True):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_dump(v, pretty))


# ---- csv --------------------------------------------------------------------

def csv_parse(s, delim=",", header=True):
    rows = list(csv.reader(io.StringIO(s), delimiter=delim))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        return []
    if not header:
        return rows
    cols = [c.strip() for c in rows[0]]
    out = []
    for r in rows[1:]:
        d = {}
        for i, c in enumerate(cols):
            d[c] = r[i] if i < len(r) else ""
        out.append(d)
    return out


def csv_dump(rows, delim=",", header=True):
    if not rows:
        return ""
    buf = io.StringIO()
    dicts = [r for r in rows if isinstance(r, dict)]
    if header and dicts and len(dicts) == len(rows):
        cols = []
        for r in rows:
            for k in r.keys():
                if k not in cols:
                    cols.append(k)
        w = csv.writer(buf, delimiter=delim, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([ox_str(r.get(c, "")) for c in cols])
    else:
        w = csv.writer(buf, delimiter=delim, lineterminator="\n")
        for r in rows:
            w.writerow([ox_str(x) for x in r])
    return buf.getvalue()


def read_csv(path, delim=",", header=True):
    with open(path, encoding="utf-8", newline="") as f:
        return csv_parse(f.read(), delim=delim, header=header)


def write_csv(path, rows, delim=",", header=True):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(csv_dump(rows, delim=delim, header=header))


# ---- yaml / toml --------------------------------------------------------------

def yaml_parse(s):
    if _yaml is None:
        raise ValueError("PyYAML is not installed on this host "
                         "(pip install pyyaml)")
    return _yaml.safe_load(s)


def yaml_dump(v):
    if _yaml is None:
        raise ValueError("PyYAML is not installed on this host "
                         "(pip install pyyaml)")
    return _yaml.safe_dump(v, sort_keys=False, allow_unicode=True)


def toml_parse(s):
    if _tomllib is None:
        raise ValueError("TOML parsing needs Python 3.11+")
    return _tomllib.loads(s)


# ---- merge ---------------------------------------------------------------------

def _deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def merge(a, b, deep=False):
    if not (isinstance(a, dict) and isinstance(b, dict)):
        raise TypeError("merge() expects two dicts")
    return _deep_merge(a, b) if deep else {**a, **b}


# ---- schema validation -----------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://[^\s]+$")


def _type_ok(v, t):
    t = t.strip()
    if t.endswith("?"):
        return v is None or _type_ok(v, t[:-1])
    if "|" in t:
        return any(_type_ok(v, part) for part in t.split("|"))
    if t == "any":
        return True
    if t == "str":
        return isinstance(v, str)
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "float":
        return isinstance(v, float)
    if t == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "bool":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    if t == "list":
        return isinstance(v, list)
    if t == "dict":
        return isinstance(v, dict)
    if t == "email":
        return isinstance(v, str) and bool(_EMAIL_RE.match(v))
    if t == "url":
        return isinstance(v, str) and bool(_URL_RE.match(v))
    if t == "date":
        if not isinstance(v, str):
            return False
        try:
            datetime.strptime(v[:10], "%Y-%m-%d")
            return True
        except ValueError:
            return False
    return False


async def validate(interp, value, schema):
    """Validate a value against a schema; returns {ok, errors}.

    Schema values: type strings ("str", "int?", "int|str", "email", ...),
    [subtype] for lists, nested dicts for dicts, or a predicate fn(v)->bool.
    A "_strict": true key in a dict schema forbids extra keys.
    """
    from ..values import call_value
    errors = []
    await _validate_walk(interp, value, schema, "$", errors)
    return {"ok": not errors, "errors": errors}


async def _validate_walk(interp, v, schema, path, errors):
    from ..values import call_value
    if isinstance(schema, (OxFunction, BuiltinFunction, BoundMethod)) or \
            (callable(schema) and not isinstance(schema, (str, list, dict))):
        try:
            ok = truthy(await call_value(interp, schema, [v]))
        except Exception as e:  # noqa: BLE001 — predicate errors become messages
            errors.append({"path": path, "msg": "predicate raised: %s" % e})
            return
        if not ok:
            errors.append({"path": path, "msg": "failed custom check"})
        return
    if isinstance(schema, str):
        if not _type_ok(v, schema):
            errors.append({"path": path,
                           "msg": "expected %s, got %s" % (schema, type_name(v))})
        return
    if isinstance(schema, list):
        if not isinstance(v, list):
            errors.append({"path": path,
                           "msg": "expected list, got %s" % type_name(v)})
            return
        sub = schema[0] if schema else "any"
        for i, item in enumerate(v):
            await _validate_walk(interp, item, sub, "%s[%d]" % (path, i), errors)
        return
    if isinstance(schema, dict):
        if not isinstance(v, dict):
            errors.append({"path": path,
                           "msg": "expected dict, got %s" % type_name(v)})
            return
        strict = truthy(schema.get("_strict", False))
        for k, sub in schema.items():
            if k == "_strict":
                continue
            if k in v:
                await _validate_walk(interp, v[k], sub, "%s.%s" % (path, k),
                                     errors)
            elif not (isinstance(sub, str) and sub.endswith("?")):
                errors.append({"path": "%s.%s" % (path, k),
                               "msg": "missing required key '%s'" % k})
        if strict:
            for k in v:
                if k not in schema:
                    errors.append({"path": "%s.%s" % (path, k),
                                   "msg": "unexpected key '%s' (strict schema)"
                                          % k})
        return
    errors.append({"path": path, "msg": "invalid schema entry %s" % ox_repr(schema)})


# ---- module ----------------------------------------------------------------------

def build():
    return NativeModule("data", {
        "json_parse": builtin("json_parse")(json_parse),
        "json_dump": builtin("json_dump")(json_dump),
        "read_json": builtin("read_json")(read_json),
        "write_json": builtin("write_json")(write_json),
        "csv_parse": builtin("csv_parse")(csv_parse),
        "csv_dump": builtin("csv_dump")(csv_dump),
        "read_csv": builtin("read_csv")(read_csv),
        "write_csv": builtin("write_csv")(write_csv),
        "yaml_parse": builtin("yaml_parse")(yaml_parse),
        "yaml_dump": builtin("yaml_dump")(yaml_dump),
        "toml_parse": builtin("toml_parse")(toml_parse),
        "merge": builtin("merge")(merge),
        "validate": builtin("validate", needs_interp=True)(validate),
    })


def build_json():
    return NativeModule("json", {
        "parse": builtin("parse")(json_parse),
        "dump": builtin("dump")(json_dump),
        "read": builtin("read")(read_json),
        "write": builtin("write")(write_json),
    })
