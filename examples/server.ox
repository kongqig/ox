# server.ox — HTTP API + static files + websockets in one place
# run: ox run examples/server.ox   (Ctrl+C to stop)

import fs
import time

let pub = fs.temp_dir("ox-static")
fs.write(f"{pub}/index.html", """
<!doctype html>
<html><head><title>ox</title></head>
<body style=\"font-family: sans-serif; margin: 3rem\">
  <h1>hello from ox</h1>
  <p>served by a ~1KB asyncio server written in the ox stdlib.</p>
</body></html>
""")

serve 8899 {

  get "/" {
    res.html("<h1>ox server</h1><p>try <a href='/api/time'>/api/time</a>, <a href='/hello/you'>/hello/you</a> or <a href='/assets/index.html'>static files</a></p>")
  }

  get "/api/time" {
    res.json({now: time.now_str(), epoch: time.epoch(), iso: time.iso()})
  }

  get "/hello/:name" {
    res.json({hello: req.params.name, method: req.method, ip: req.ip})
  }

  get "/search" {
    let q = req.query.get("q", "")
    res.json({query: q, results: []})
  }

  post "/api/echo" {
    res.json({you_sent: req.json, bytes: req.body.len()})
  }

  put "/api/items/:id" {
    res.json({updated: req.params.id, body: req.json}, status=200)
  }

  get "/error" {
    throw error("this becomes a 500", code=1234)
  }

  static "/assets" pub

  ws "/ws/echo" {
    conn.on("message", fn (msg) {
        conn.send(f"echo: {msg}")
      })
  }
}
