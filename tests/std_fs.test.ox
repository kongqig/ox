import fs
import verify

var tmp = fs.temp_dir("ox-fs-test")

test "write/read/append" {
  let p = fs.join(tmp, "a.txt")
  verify.eq(fs.write(p, "one
"), 4)
  fs.append(p, "two
")
  verify.eq(fs.read(p), "one
two
")
  verify.eq(fs.read_lines(p), ["one", "two"])
  verify.eq(fs.write_lines(fs.join(tmp, "lines.txt"), ["x", "y"]), 2)
}

test "exists/size/type" {
  let p = fs.join(tmp, "a.txt")
  verify.true(fs.exists(p))
  verify.true(fs.is_file(p))
  verify.false(fs.is_dir(p))
  verify.eq(fs.size(p), 8)
  verify.false(fs.empty(p))
  fs.touch(fs.join(tmp, "empty.txt"))
  verify.true(fs.empty(fs.join(tmp, "empty.txt")))
}

test "dirs, walk, glob" {
  fs.mkdirs(fs.join(tmp, "d1/d2"))
  fs.write(fs.join(tmp, "d1/f1.log"), "x")
  fs.write(fs.join(tmp, "d1/d2/f2.log"), "y")
  fs.write(fs.join(tmp, "d1/f3.txt"), "z")
  verify.true(fs.is_dir(fs.join(tmp, "d1/d2")))
  verify.eq(fs.walk(fs.join(tmp, "d1")).len(), 3)
  verify.eq(fs.walk(fs.join(tmp, "d1"), pattern="*.log").len(), 2)
  verify.eq(fs.files(fs.join(tmp, "d1")).sort(), ["f1.log", "f3.txt"])
  verify.eq(fs.dirs(tmp).has("d1"), true)
  verify.eq(fs.list(fs.join(tmp, "d1")).len(), 3)
}

test "copy/move/remove" {
  let a = fs.join(tmp, "a.txt")
  let b = fs.join(tmp, "b.txt")
  fs.copy(a, b)
  verify.eq(fs.read(b), fs.read(a))
  fs.move(b, fs.join(tmp, "c.txt"))
  verify.false(fs.exists(b))
  verify.true(fs.exists(fs.join(tmp, "c.txt")))
  fs.remove(fs.join(tmp, "c.txt"))
  verify.false(fs.exists(fs.join(tmp, "c.txt")))
}

test "json round trip" {
  let p = fs.join(tmp, "data.json")
  fs.write_json(p, {name: "ox", tags: ["a", "b"], n: {deep: true}})
  let d = fs.read_json(p)
  verify.eq(d.name, "ox")
  verify.eq(d.tags, ["a", "b"])
  verify.true(d.n.deep)
}

test "path helpers" {
  verify.eq(fs.join("a", "b", "c.txt"), "a/b/c.txt")
  verify.eq(fs.ext("x/y.tar.gz"), ".gz")
  verify.eq(fs.stem("x/y.tar.gz"), "y.tar")
  verify.eq(fs.split("a/b/c"), ["a/b", "c"])
  verify.true(fs.abs("x").has("/"))
}

test "grep and replace" {
  let p = fs.join(tmp, "grep.txt")
  fs.write(p, "alpha
beta
gamma
")
  verify.eq(fs.grep(p, "a").len(), 3)
  verify.eq(fs.grep(p, "beta").len(), 1)
  verify.eq(fs.replace(p, "beta", "BETA"), 1)
  verify.true(fs.read(p).has("BETA"))
}

test "hashes" {
  let p = fs.join(tmp, "hash.txt")
  fs.write(p, "hello")
  verify.eq(fs.sha256(p).len(), 64)
  verify.eq(fs.md5(p), "5d41402abc4b2a76b9719d911017c592")
}

test "watch sees changes" {
  var events = []
  let p = fs.join(tmp, "watched.txt")
  fs.write(p, "v1")
  let w = fs.watch(tmp, fn (evt) {
      if evt.path == p { events.push(evt.kind) }
    }, interval=0.05)
  await sleep(150ms)
  fs.write(p, "v2")
  await sleep(250ms)
  w.stop()
  verify.true(events.len() >= 1, f"expected at least one event, got {events}")
}

test "remove_tree is idempotent (rm -rf semantics)" {
  let d = fs.temp_dir("ox-rmtree")
  fs.mkdirs(fs.join(d, "a/b"))
  fs.write(fs.join(d, "a/b/f.txt"), "x")
  fs.remove_tree(fs.join(d, "a"))
  verify.false(fs.exists(fs.join(d, "a")))
  # gone means gone — not an error
  fs.remove_tree(fs.join(d, "a"))
  verify.false(fs.exists(fs.join(d, "a")))
  fs.remove_tree(d)
}
