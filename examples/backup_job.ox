# backup_job.ox — snapshot -> archive -> checksum -> verify -> prune
#
# The canonical automation job. Demonstrates the full workflow machinery:
# steps with values, rollback of the failed step's partial work, persisted
# state (.ox/state), cross-run pruning, and resume after failure.
#
#   python -m ox run examples/backup_job.ox               # normal run
#   OX_FAIL=1 python -m ox run examples/backup_job.ox     # fail once, auto-resume
#   python -m ox run examples/backup_job.ox               # run again (prune)
#
# Note: rollbacks are compensating — a rollback attached to step X also
# fires when a LATER step fails. Combining that with resume=true (which
# credits already-ok steps) can undo work that resume then assumes exists,
# so this job keeps rollbacks scoped to the step that owns the partial work.

import crypto
import env
import fs
import log
import time
import wf

let work = env.get("OX_BACKUP_HOME") ??
fs.join(fs.temp_dir("ox-backup-demo"), "home")
let data_dir = fs.join(work, "data")
let backup_dir = fs.join(work, "backups")
fs.mkdirs(data_dir)
fs.mkdirs(backup_dir)
wf.state_dir(fs.join(work, ".state"))

let keep = 3

# seed "application data" on first run
if fs.files(data_dir).empty() {
  fs.write(fs.join(data_dir, "notes.md"), "# notes
nothing to see here
")
  fs.write(fs.join(data_dir, "config.json"),
    '{"theme": "dark", "retries": 3, "feature_flags": {}}')
  fs.write(fs.join(data_dir, "run.log"),
    "started
ok
ok
ok
stopped
")
  print("seeded " + str(fs.files(data_dir).len()) + " files into " + data_dir)
}

fn latest_archive() {
  let all = fs.glob(fs.join(backup_dir, "backup-*.zip")).sort()
  if all.empty() { throw error("no archive found in " + backup_dir) }
  return all.last()
}

workflow "backup" {
  desc "snapshot, archive, checksum, verify, prune"

  step "snapshot" {
    # stage a consistent copy of the data directory
    fs.remove_tree(fs.join(work, "staging"))
    fs.copytree(data_dir, fs.join(work, "staging"))
    if fs.files(fs.join(work, "staging")).empty() {
      throw error("snapshot came out empty")
    }
    fs.files(fs.join(work, "staging")).len()
  }

  step "archive" {
    let stamp = time.now_str("%Y%m%d-%H%M%S")
    let dest = fs.join(backup_dir, "backup-" + stamp + ".zip")
    let staging = fs.join(work, "staging")
    let n = fs.zip([staging], dest, base=staging)
    if n == 0 {
      fs.remove(dest) # don't leave an empty archive behind
      throw error("archive is empty")
    }
    dest
  }

  step "checksum" {
    let a = latest_archive()
    let sum = crypto.hash_file(a)
    fs.write(a + ".sha256", sum + "  " + fs.split(a).last())
    sum
  }

  step "verify" {
    let a = latest_archive()
    let recorded = fs.read(a + ".sha256").split("  ")[0]
    verify fs.size(a) > 0, "archive is empty"
    verify crypto.hash_file(a) == recorded, "checksum mismatch"
    "integrity ok"
  }

  step "publish" {
    # copy the verified archive to the "published" location
    if env.get("OX_FAIL") == "1" and not fs.exists(fs.join(work, ".failed-once")) {
      fs.write(fs.join(work, ".failed-once"), "1")
      throw error("simulated publish failure (OX_FAIL=1, first attempt only)")
    }
    let a = latest_archive()
    let pub = fs.join(work, "published")
    fs.remove_tree(pub)
    fs.mkdirs(pub)
    fs.copy(a, fs.join(pub, fs.split(a).last()))
    fs.copy(a + ".sha256", fs.join(pub, fs.split(a).last() + ".sha256"))
    "published " + fs.split(a).last()
  } rollback {
    fs.remove_tree(fs.join(work, "published"))
  }

  step "report" {
    let a = latest_archive()
    let st = wf.status("backup")
    "kept " + str(fs.glob(fs.join(backup_dir, "backup-*.zip")).len()) +
    " archives, latest " + fs.split(a).last() + " (" +
    str((fs.size(a) / 1024.0).round(1)) + " KB)"
  }

  step "prune" {
    let all = fs.glob(fs.join(backup_dir, "backup-*.zip")).sort()
    let excess = all.len() - keep
    if excess > 0 {
      for old in all.slice(0, excess) {
        fs.remove(old)
        fs.remove(old + ".sha256")
      }
      "pruned " + str(excess) + " old archive(s)"
    } else {
      "nothing to prune (" + str(all.len()) + " <= " + str(keep) + ")"
    }
  }

  on fail { log.error("backup failed — re-run to resume from the last ok step") }
  on done { log.info("backup finished: " + str(fs.glob(fs.join(backup_dir, "backup-*.zip")).len()) + " archives kept") }
}

# optional failure injection: the publish step fails once, then the
# script resumes and finishes the job
if env.get("OX_FAIL") == "1" {
  print("NOTE: OX_FAIL=1 — publish will fail on its first attempt, then resume")
}

var r = run("backup")
if not r.ok {
  print("")
  print("-- resuming: already-ok steps are skipped --")
  r = run("backup", resume=true)
}
print("")
print("run " + str(r.run) + " " + r.status + " in " + str(r.ms) + "ms")
for s in r.steps {
  print("  " + s.name.pad_right(10) + " " + s.status.pad_right(18) +
    " " + str(s.ms) + "ms")
}
if not r.ok {
  print("rolled back: " + r.rolled_back.join(", "))
  print("re-run without OX_FAIL to resume from the last ok step")
}
print("")
print("backups now in " + backup_dir + ":")
for f in fs.glob(fs.join(backup_dir, "backup-*.zip")).sort() {
  print("  " + fs.split(f).last().pad_right(28) +
    str((fs.size(f) / 1024.0).round(1)) + " KB")
}
