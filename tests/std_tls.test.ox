# TLS end-to-end: a self-signed certificate, a real https/wss server,
# and a client that must both succeed (verify=false) and refuse
# (verify=true). Certificates are generated at fixture time via the
# py bridge (cryptography) with an openssl fallback; when neither is
# available the tests report as skipped instead of failing.

import fs
import net
import py
import verify

fn tmpdir() {
  return fs.temp_dir("ox-tls")
}

# ---- fixture: one self-signed cert for 127.0.0.1 ----------------------------

var tls_ready = false
var tls_dir = ""

let _d = tmpdir()
fs.mkdirs(_d)
py.exec("TLS_DIR = '" + _d + "'")
py.exec("""
import datetime, ipaddress, os
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, \"127.0.0.1\")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(\"127.0.0.1\"))]),
                critical=False)
            .sign(key, hashes.SHA256()))
    with open(os.path.join(TLS_DIR, \"cert.pem\"), \"wb\") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(os.path.join(TLS_DIR, \"key.pem\"), \"wb\") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    TLS_OK = True
except ImportError:
    import subprocess
    cmd = [\"openssl\", \"req\", \"-x509\", \"-newkey\", \"rsa:2048\", \"-nodes\",
           \"-keyout\", os.path.join(TLS_DIR, \"key.pem\"),
           \"-out\", os.path.join(TLS_DIR, \"cert.pem\"),
           \"-days\", \"2\", \"-subj\", \"/CN=127.0.0.1\",
           \"-addext\", \"subjectAltName=IP:127.0.0.1\"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    TLS_OK = r.returncode == 0
""")
tls_ready = py.eval("TLS_OK") == true
tls_dir = _d

fn require_tls() {
  if not tls_ready {
    verify.skip("no certificate tooling (cryptography/openssl) available")
  }
}

fn start_tls_server() {
  return serve 0, daemon = true, tls = {cert: tls_dir + "/cert.pem",
    key: tls_dir + "/key.pem"} {
    get "/hi" { res.json({msg: "secure hi"}) }
    ws "/echo" {
      conn.on("message", fn (m) { conn.send("echo: " + m) })
    }
  }
}

# ---- https ------------------------------------------------------------------

test "https: self-signed cert serves requests with verify=false", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  verify.true(h.url.startswith("https://"))
  let r = net.get(h.url + "/hi", verify=false, timeout=5)
  verify.eq(r.status, 200)
  verify.eq(r.json.msg, "secure hi")
  h.stop()
}

test "https: certificate verification rejects a self-signed cert", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  let r = net.get(h.url + "/hi", verify=true, timeout=5)
  verify.false(r.ok)
  verify.eq(r.status, 0)
  verify.true(r.reason.contains("CERTIFICATE_VERIFY_FAILED"))
  h.stop()
}

test "plain http to a TLS port fails cleanly (no hang, no 200)", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  let r = net.get("http://127.0.0.1:" + str(h.port) + "/hi", timeout=5)
  verify.false(r.ok)
  verify.eq(r.status, 0)
  h.stop()
}

test "https: net.download honors verify=false", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  let to = fs.join(tmpdir(), "dl-body.txt")
  let r = net.download(h.url + "/hi", to, verify=false, timeout=5)
  verify.true(r.ok)
  verify.true(r.size > 0)
  verify.true(fs.read(to).contains("secure hi"))
  fs.remove(to)
  h.stop()
}

test "serve tls= reports unusable options as errors, not tracebacks" {
  let e1 = verify.throws(fn () {
      serve 0, daemon=true, tls="junk" {
        get "/" { res.send("x") }
      }
    })
  verify.true(e1.msg.contains("tls="))

  let e2 = verify.throws(fn () {
      serve 0, daemon=true, tls={cert: "/no/such/cert.pem",
        key: "/no/such/key.pem"} {
        get "/missing" { res.send("x") }
      }
    })
  verify.true(e2.msg.contains("certificate"))
}

# ---- wss --------------------------------------------------------------------

test "wss: self-signed websocket roundtrip with verify=false", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  let c = net.ws("wss://127.0.0.1:" + str(h.port) + "/echo",
    verify=false, timeout=5)
  c.send("hello wss")
  let reply = c.recv(timeout=2s)
  verify.eq(reply, "echo: hello wss")
  c.close()
  h.stop()
}

test "wss: verification rejects a self-signed cert", timeout = 10s {
  require_tls()
  let h = start_tls_server()
  let e = verify.throws(fn () {
      net.ws("wss://127.0.0.1:" + str(h.port) + "/echo", verify=true,
        timeout=5)
    })
  verify.true(e.msg.contains("CERTIFICATE_VERIFY_FAILED"))
  h.stop()
}
