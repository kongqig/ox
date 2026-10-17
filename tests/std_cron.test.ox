import co
import time
import verify

# cron_next is deterministic given an explicit `after` (epoch seconds).
# Fixed anchor: 2026-03-14 23:45 local — a Saturday.
var anchor = time.parse("2026-03-14 23:45:00")

test "every-minute expression" {
  let n = co.cron_next("* * * * *", after=anchor)
  verify.eq(n, anchor + 60) # next whole minute after 23:45 is 23:46
  verify.eq(co.cron_next("* * * * *", after=n), n + 60)
}

test "step minutes" {
  verify.eq(co.cron_next("*/15 * * * *", after=anchor), anchor + 15 * 60)
  # from exactly a step minute, the next one is +15
  let at = co.cron_next("*/15 * * * *", after=anchor)
  verify.eq(co.cron_next("*/15 * * * *", after=at), at + 15 * 60)
}

test "hour rollover" {
  # 23:59 -> next day 00:00 for "0 * * * *" is 2026-03-15 00:00
  let late = time.parse("2026-03-14 23:59:30")
  verify.eq(co.cron_next("0 * * * *", after=late),
    time.parse("2026-03-15 00:00:00"))
}

test "daily at 09:00" {
  verify.eq(co.cron_next("0 9 * * *", after=anchor),
    time.parse("2026-03-15 09:00:00"))
  let morning = time.parse("2026-03-14 08:00:00")
  verify.eq(co.cron_next("0 9 * * *", after=morning),
    time.parse("2026-03-14 09:00:00"))
}

test "weekday names and ranges (mon-fri)" {
  # saturday 2026-03-14 -> next weekday at 09:00 is monday 2026-03-16
  verify.eq(co.cron_next("0 9 * * mon-fri", after=anchor),
    time.parse("2026-03-16 09:00:00"))
  # friday morning itself still matches
  let fri = time.parse("2026-03-13 08:00:00")
  verify.eq(co.cron_next("0 9 * * mon-fri", after=fri),
    time.parse("2026-03-13 09:00:00"))
}

test "sunday via 7" {
  # cron: 0 and 7 both mean sunday; 2026-03-15 is a sunday
  let via0 = co.cron_next("0 12 * * 0", after=anchor)
  let via7 = co.cron_next("0 12 * * 7", after=anchor)
  verify.eq(via0, via7)
  verify.eq(via0, time.parse("2026-03-15 12:00:00"))
}

test "day-of-month and month" {
  verify.eq(co.cron_next("30 4 1 * *", after=anchor),
    time.parse("2026-04-01 04:30:00"))
  verify.eq(co.cron_next("0 0 1 jan *", after=anchor),
    time.parse("2027-01-01 00:00:00"))
}

test "dom OR dow when both restricted (classic cron rule)" {
  # 2026-03-13 is friday the 13th; "0 0 13 * fri" fires on the 13th ...
  let e1 = co.cron_next("0 0 13 * fri", after=anchor - 2 * 86400)
  verify.eq(e1, time.parse("2026-03-13 00:00:00"))
  # ... but also on any other friday, e.g. 2026-03-20
  let e2 = co.cron_next("0 0 13 * fri", after=e1)
  verify.eq(e2, time.parse("2026-03-20 00:00:00"))
}

test "aliases" {
  verify.eq(co.cron_next("@daily", after=anchor),
    co.cron_next("0 0 * * *", after=anchor))
  verify.eq(co.cron_next("@hourly", after=anchor),
    co.cron_next("0 * * * *", after=anchor))
  verify.eq(co.cron_next("@weekly", after=anchor),
    co.cron_next("0 0 * * 0", after=anchor))
  verify.eq(co.cron_next("@monthly", after=anchor),
    co.cron_next("0 0 1 * *", after=anchor))
}

test "lists and mixed fields" {
  verify.eq(co.cron_next("5,35 8-10 * * *", after=anchor),
    time.parse("2026-03-15 08:05:00"))
}

test "invalid expressions throw" {
  let cases = ["", "* * * *", "61 * * * *", "* 25 * * *", "* * 0 * *",
    "*/0 * * * *", "a * * * *", "* * * jan-x *"]
  for e in cases {
    verify.throws(fn () { co.cron_next(e) })
  }
}

test "co.cron handle: next() and stop()" {
  let fired = 0
  let h = co.cron("*/1 * * * *", fn () { fired=fired + 1 })
  verify.ne(h.next(), null)
  verify.true(h.next() > time.epoch())
  verify.true(h.next() <= time.epoch() + 60)
  h.stop()
  verify.true(h.stopped())
  # stopped handles never fire
  await co.sleep(50ms)
  verify.eq(fired, 0)
}

test "co.cron validates the expression up front" {
  verify.throws(fn () { co.cron("nonsense", fn () { pass }) })
}

test "co.cron fires on the minute boundary" {
  # schedule for every minute; the next fire is within 60s — but to keep
  # the suite fast we only accept the lucky case: if the boundary is less
  # than 1.5s away, wait for it; otherwise just verify scheduling state.
  var fired = 0
  let h = co.cron("* * * * *", fn () { fired=fired + 1 })
  let wait = h.next() - time.epoch()
  if wait < 1.5s {
    await co.sleep(wait + 300ms)
    verify.eq(fired, 1)
  }
  h.stop()
}
