# backup.ox — workflows: steps, retries, rollback, persisted state
# run: ox run examples/backup.ox

import fs
import log
import os
import time
import wf

let work = fs.temp_dir("ox-backup")
log.info(f"demo workspace: {work}")

workflow "backup" {
  desc "Dump, compress, upload, verify — with rollback on failure"

  step "dump" {
    fs.write(f"{work}/db.sql", "-- fake dump
" + "INSERT INTO ox VALUES (1);
" * 500)
    verify fs.size(f"{work}/db.sql") > 100, "dump must not be empty"
    f"dumped {fs.size(f"{work}/db.sql")} bytes"
  }

  step "compress" {
    sh(f"gzip -k -f {work}/db.sql")
    verify fs.exists(f"{work}/db.sql.gz"), "gzip should produce the archive"
  } rollback {
    fs.remove(f"{work}/db.sql.gz")
  }

  step "upload" {
    # pretend the network is flaky: fails once, then succeeds
    if not fs.exists(f"{work}/.attempted") {
      fs.write(f"{work}/.attempted", "1")
      throw error("connection reset by peer")
    }
    fs.copy(f"{work}/db.sql.gz", f"{work}/remote-backup.gz")
    "uploaded"
  } retry 3 backoff 100ms

  step "verify" {
    verify fs.size(f"{work}/remote-backup.gz") == fs.size(f"{work}/db.sql.gz"),
    "remote copy must match local archive"
  }

  on fail { log.error("backup failed — check wf.history('backup')") }
  on done { emit "backup.ok" {host: os.hostname(), at: time.now()} }
}

on "backup.ok" fn (evt) {
  log.ok(f"event received: backup of {evt.host} finished")
}

# a real run (the flaky upload retries once and then passes)
let r = run("backup")
verify r.ok, "backup should succeed after retrying the flaky upload"

# inspect the persisted history
log.table(wf.history("backup"), cols=["id", "status", "ms"])
log.info(f"steps: {wf.steps('backup').join(' -> ')}")

# a dry run shows the plan without executing anything
let d = run("backup", dry=true)
verify d.steps.len() == 4

# cleanup
fs.remove_tree(work)
log.ok("workflow demo complete")
