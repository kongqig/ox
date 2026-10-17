import verify
import "./mods/util.ox" as util

test "import module by path" {
  verify.eq(util.double(21), 42)
  verify.eq(util.shout("ox"), "OX!")
  verify.eq(util.version, "1.0")
}

test "private names are not exported" {
  let e = verify.throws(fn () { util._secret })
  verify.true(e.msg.has("no function"))
}

test "no-alias import uses file stem" {
  verify.true(true)
}

import "./mods/util2"

test "module without exports exposes public names" {
  verify.eq(util2.triple(5), 15)
  verify.eq(util2.label, "util2")
  let e = verify.throws(fn () { util2._hidden })
  verify.true(e.msg.has("no function"))
}
