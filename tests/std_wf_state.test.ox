# Workflow state persistence: corruption recovery, crash visibility,
# and the one-live-run lock (the 0.4.1 hardening — see taskmod.py).

import co
import fs
import verify
import wf

wf.state_dir(fs.temp_dir("ox-wf-recovery"))

fn state_file(name) {
  return fs.join(wf.state_dir(), name + ".json")
}

test "truncated state file is backed up and recovered" {
  let p = state_file("trunc")
  fs.write(p, '{"name": "trunc", "runs": [{"id": 1, "sta')
  workflow "trunc" { step "s" { "v" } }
  let r = run("trunc")
  verify.true(r.ok)
  verify.true(fs.exists(p + ".corrupt"))
  verify.eq(wf.status("trunc").runs, 1)
}

test "garbage state file is backed up and recovered" {
  let p = state_file("garbage")
  fs.write(p, "}}} not json at all {{{")
  workflow "garbage" { step "s" { 1 } }
  let r = run("garbage")
  verify.true(r.ok)
  verify.true(fs.exists(p + ".corrupt"))
  verify.eq(wf.status("garbage").last.status, "ok")
}

test "valid json with wrong shape recovers without a traceback" {
  let p = state_file("shape")
  fs.write(p, '{"runs": 42}')
  workflow "shape" { step "s" { 1 } }
  let r = run("shape")
  verify.true(r.ok)
  verify.true(fs.exists(p + ".corrupt"))
  # an empty object is equally unusable — must not crash either
  fs.write(p, "{}")
  let r2 = run("shape")
  verify.true(r2.ok)
}

test "malformed run records are dropped, valid ones salvaged" {
  let p = state_file("salvage")
  fs.write(p, '{"name": "salvage", "runs": [' +
    '{"id": 1, "steps": [{"name": "a", "status": "ok"}]},' +
    ' "junk", 7]}')
  let st = wf.status("salvage")
  verify.eq(st.runs, 1)
  verify.eq(st.last.id, 1)
  verify.eq(st.last.steps[0].name, "a")
  verify.true(fs.exists(p + ".corrupt"))
}

test "repeated corruption gets numbered backups" {
  let p = state_file("twice")
  workflow "twice" { step "s" { 1 } }
  run("twice")
  fs.write(p, "garbage-one")
  run("twice")
  fs.write(p, "garbage-two")
  run("twice")
  verify.true(fs.exists(p + ".corrupt"))
  verify.true(fs.exists(p + ".corrupt-1"))
  verify.eq(wf.status("twice").last.status, "ok")
}

test "a run killed mid-flight is resumable (running record = crashed)" {
  let p = state_file("crashed")
  # what the state file looks like after the process died at step "two"
  fs.write(p, '{"name": "crashed", "runs": [{"id": 1, "started": 1.0, ' +
    '"status": "running", "mode": "normal", "ms": 0, "steps": [' +
    '{"name": "one", "status": "ok", "attempts": 1, "ms": 5, "error": null},' +
    '{"name": "two", "status": "pending", "attempts": 0, "ms": 0, "error": null}]}]}')
  var trace = []
  workflow "crashed" {
    step "one" { trace.push("one") }
    step "two" { trace.push("two") }
  }
  verify.eq(wf.status("crashed").last.status, "running")
  let r = run("crashed", resume=true)
  verify.true(r.ok)
  verify.eq(trace, ["two"])
  verify.eq(r.mode, "resume")
  verify.eq(r.steps[0].status, "skipped (resume)")
  verify.eq(r.steps[1].status, "ok")
  verify.eq(wf.status("crashed").last.status, "ok")
}

test "run is persisted as running before its first step executes" {
  var seen = []
  workflow "persist-check" {
    step "look" {
      # in-flight: the state file must already show this run
      seen.push(wf.status("persist-check").last.status)
    }
  }
  run("persist-check")
  verify.eq(seen, ["running"])
  verify.eq(wf.status("persist-check").last.status, "ok")
}

test "a second concurrent run of the same workflow is rejected" {
  workflow "guard" {
    step "slow" { co.sleep(500ms) }
  }
  let h = co.after(1ms, fn () { run("guard") })
  co.sleep(150ms) # first run must hold the lock by now
  let e = verify.throws(fn () { run("guard") })
  verify.true(e.msg.contains("already running"))
  co.sleep(600ms) # let the first run finish cleanly
  verify.eq(wf.status("guard").last.status, "ok")
  h.stop()
}

test "cross-process crash leaves a running record; resume recovers it", timeout = 30s {
  let d = fs.temp_dir("ox-wf-crash")
  fs.mkdirs(d)
  let marker = fs.join(d, "marker.txt")
  let script = fs.join(d, "crashy.ox")

  # the child script reads its knobs from the environment, so nothing
  # has to be spliced into the source; on resume the "boom" step no-ops
  fs.write(script, 'import env
import fs
import os

' +
    'let marker = env.get("OX_MARK")

' +
    'workflow "crashy" {
' +
    '  step "part-one" { fs.write(marker, "one") }
' +
    '  step "boom" {
' +
    '    if env.get("OX_RESUME") != "1" {
' +
    '      sh("kill -9 " + str(os.pid()))
' +
    '    }
' +
    '  }
' +
    '  step "part-two" { fs.write(marker, "two") }
' +
    '}

' +
    'if env.get("OX_RESUME") == "1" {
' +
    '  run("crashy", resume=true)
' +
    '} else {
' +
    '  run("crashy")
' +
    '}
')

  let r1 = sh("python -m ox run " + script, env={OX_MARK: marker},
    timeout=20s)
  verify.false(r1.ok) # killed with SIGKILL mid-run
  verify.eq(fs.read(marker), "one") # part-one did run before the crash

  let r2 = sh("python -m ox run " + script,
    env={OX_MARK: marker, OX_RESUME: "1"}, timeout=20s)
  verify.true(r2.ok)
  verify.eq(fs.read(marker), "two") # part-two completed, part-one skipped
  fs.remove_tree(d)
}
