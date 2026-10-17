import fs
import wf
import verify

wf.state_dir(fs.temp_dir("ox-wf-state"))

var trace = []

test "successful workflow" {
  trace = []
  workflow "ok-flow" {
    desc "everything works"
    step "one" { trace.push(1)
      "first" }
    step "two" { trace.push(2) }
    on done { trace.push("done") }
  }
  let r = run("ok-flow")
  verify.true(r.ok)
  verify.eq(r.status, "ok")
  verify.eq(trace, [1, 2, "done"])
  verify.eq(r.steps.len(), 2)
  verify.eq(r.steps[0].status, "ok")
  verify.eq(wf.steps("ok-flow"), ["one", "two"])
}

test "failing workflow: retry, rollback, hooks, state" {
  trace = []
  workflow "bad-flow" {
    step "prep" { trace.push("prep") }
    step "do" {
      trace.push("do")
      throw error("disk full")
    } retry 3 backoff 5ms rollback {
      trace.push("undo-do")
    }
    step "never" { trace.push("never") }
    on fail { trace.push("failed") }
  }
  let r = run("bad-flow")
  verify.false(r.ok)
  verify.eq(r.status, "failed")
  verify.eq(r.steps[1].attempts, 3)
  verify.eq(trace, ["prep", "do", "do", "do", "undo-do", "failed"])
  verify.eq(r.rolled_back, ["do"])
  let st = wf.status("bad-flow")
  verify.eq(st.last.status, "failed")
  verify.true(st.runs >= 1)
}

test "history accumulates" {
  workflow "hist" { step "s" { pass } }
  run("hist")
  run("hist")
  run("hist")
  verify.eq(wf.history("hist").len(), 3)
  verify.eq(wf.history("hist", n=2).len(), 2)
  verify.eq(wf.history("hist")[2].status, "ok")
}

test "dry run" {
  trace = []
  workflow "dried" { step "a" { trace.push("x") } }
  let r = run("dried", dry=true)
  verify.true(r.ok)
  verify.eq(trace, [])
  verify.eq(r.steps[0].status, "dry")
}

test "only= partial run skips hooks" {
  trace = []
  workflow "partial" {
    step "a" { trace.push("a") }
    step "b" { trace.push("b") }
    on done { trace.push("hook") }
  }
  let r = run("partial", only=["a"])
  verify.true(r.ok)
  verify.eq(trace, ["a"])
}

test "resume skips completed steps" {
  trace = []
  workflow "resumable" {
    step "first" { trace.push("first") }
    step "second" { throw error("nope") }
    step "third" { trace.push("third") }
  }
  run("resumable")
  trace = []
  let r = run("resumable", resume=true)
  verify.false(r.ok)
  verify.eq(trace, [])
  verify.eq(r.steps[0].status, "skipped (resume)")
}

test "wf.list" {
  let names = wf.list().map(fn (w) { w.name })
  verify.true(names.has("ok-flow"))
  verify.true(names.has("bad-flow"))
}
