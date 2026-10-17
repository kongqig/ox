import co
import fs
import os
import verify

var tmp = fs.temp_dir("ox-lock-test")

test "lock and release" {
  let p = fs.join(tmp, "a.lock")
  let lk = fs.lock(p)
  verify.true(lk.held)
  verify.eq(lk.path, p)
  verify.true(lk.release())
  verify.false(lk.held)
}

test "try_lock: null while held, handle after release" {
  let p = fs.join(tmp, "b.lock")
  let lk = fs.try_lock(p)
  verify.ne(lk, null)
  # a second lock attempt (even in the same process) must fail
  verify.eq(fs.try_lock(p), null)
  lk.release()
  # and succeed again
  let lk2 = fs.try_lock(p)
  verify.ne(lk2, null)
  lk2.release()
}

test "lock with timeout throws when held" {
  let p = fs.join(tmp, "c.lock")
  let lk = fs.lock(p)
  let e = verify.throws(fn () { fs.lock(p, timeout=200ms) })
  verify.true(e.kind == "timeout")
  lk.release()
}

test "lock without timeout waits and acquires after release" {
  let p = fs.join(tmp, "d.lock")
  let lk = fs.lock(p)
  # spawn a task that releases the lock shortly
  spawn {
    await co.sleep(150ms)
    lk.release()
  }
  let lk2 = fs.lock(p, timeout=5s) # must succeed once released
  verify.true(lk2.held)
  lk2.release()
}

test "with_lock runs fn and always releases" {
  let p = fs.join(tmp, "e.lock")
  let seen = fs.with_lock(p, fn () { return 41 + 1 })
  verify.eq(seen, 42)
  # lock is free again
  let lk = fs.try_lock(p)
  verify.ne(lk, null)
  lk.release()
  # releases even when fn throws
  let e = verify.throws(fn () {
      fs.with_lock(p, fn () { throw error("boom") })
    })
  verify.eq(e.msg, "boom")
  let lk2 = fs.try_lock(p)
  verify.ne(lk2, null)
  lk2.release()
}

test "cross-process exclusion" {
  let p = fs.join(tmp, "xproc.lock")
  # a real other process holds the lock for a moment
  fs.write(fs.join(tmp, "holder.py"),
    "import fcntl, sys, time
" +
    "f = open(sys.argv[1], 'a+')
" +
    "fcntl.flock(f, fcntl.LOCK_EX)
" +
    "time.sleep(1)
")
  let proc = os.start(f"python3 {fs.join(tmp, 'holder.py')} " + p)
  # wait until it has certainly taken the lock
  await co.sleep(400ms)
  verify.eq(fs.try_lock(p), null)
  # blocking lock with timeout acquires it after the process exits
  let lk = fs.lock(p, timeout=5s)
  verify.true(lk.held)
  lk.release()
  let r = await proc.wait(2s)
  verify.true(r.ok)
}
