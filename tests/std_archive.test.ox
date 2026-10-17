import fs
import py
import verify

var tmp = fs.temp_dir("ox-arch-test")

test "zip/unzip roundtrip with nested dirs" {
  fs.mkdirs(fs.join(tmp, "src/nested"))
  fs.write(fs.join(tmp, "src/a.txt"), "alpha")
  fs.write(fs.join(tmp, "src/nested/b.txt"), "beta")

  let z = fs.join(tmp, "out.zip")
  verify.eq(fs.zip(fs.join(tmp, "src"), z), 2)
  verify.true(fs.exists(z))
  verify.true(fs.size(z) > 0)

  # top-level name is preserved inside the archive
  let out = fs.join(tmp, "unzipped")
  verify.eq(fs.unzip(z, out), 2)
  verify.eq(fs.read(fs.join(out, "src/a.txt")), "alpha")
  verify.eq(fs.read(fs.join(out, "src/nested/b.txt")), "beta")
}

test "zip multiple paths" {
  fs.write(fs.join(tmp, "m1.txt"), "1")
  fs.write(fs.join(tmp, "m2.txt"), "2")
  let z = fs.join(tmp, "multi.zip")
  verify.eq(fs.zip([fs.join(tmp, "m1.txt"), fs.join(tmp, "m2.txt")], z), 2)
  let out = fs.join(tmp, "multi-out")
  verify.eq(fs.unzip(z, out), 2)
  verify.eq(fs.read(fs.join(out, "m1.txt")), "1")
  verify.eq(fs.read(fs.join(out, "m2.txt")), "2")
}

test "zip with base= strips the prefix" {
  let z = fs.join(tmp, "base.zip")
  verify.eq(fs.zip(fs.join(tmp, "src/nested"), z, base=tmp), 1)
  let out = fs.join(tmp, "base-out")
  verify.eq(fs.unzip(z, out), 1)
  verify.eq(fs.read(fs.join(out, "src/nested/b.txt")), "beta")

  # base= the directory itself: entries are relative to it
  let z2 = fs.join(tmp, "base2.zip")
  verify.eq(fs.zip(fs.join(tmp, "src/nested/b.txt"), z2,
      base=fs.join(tmp, "src/nested")), 1)
  let out2 = fs.join(tmp, "base2-out")
  verify.eq(fs.unzip(z2, out2), 1)
  verify.eq(fs.read(fs.join(out2, "b.txt")), "beta")
}

test "zip missing path errors" {
  let e = verify.throws(fn () { fs.zip(fs.join(tmp, "nope"), "/tmp/x.zip") })
  verify.true(e.msg.has("no such file"))
}

test "tar_gz/untar_gz roundtrip" {
  let t = fs.join(tmp, "site.tgz")
  verify.eq(fs.tar_gz(fs.join(tmp, "src"), t), 2)
  verify.true(fs.exists(t))

  let out = fs.join(tmp, "untarred")
  verify.eq(fs.untar_gz(t, out), 2)
  verify.eq(fs.read(fs.join(out, "src/a.txt")), "alpha")
  verify.eq(fs.read(fs.join(out, "src/nested/b.txt")), "beta")
}

test "tar with a file list" {
  let t = fs.join(tmp, "files.tgz")
  verify.eq(fs.tar_gz([fs.join(tmp, "m1.txt"), fs.join(tmp, "m2.txt")], t), 2)
  let out = fs.join(tmp, "files-out")
  verify.eq(fs.untar_gz(t, out), 2)
  verify.eq(fs.read(fs.join(out, "m1.txt")), "1")
}

test "zip-slip entries are rejected" {
  # craft a malicious archive with a path-traversal entry
  py.exec(f"TMP = \"{tmp}\"")
  py.exec("""
import zipfile
with zipfile.ZipFile(TMP + '/evil.zip', 'w') as z:
    z.writestr('../evil.txt', 'pwned')
    z.writestr('safe.txt', 'fine')
""")
  let out = fs.join(tmp, "evil-out")
  let e = verify.throws(fn () { fs.unzip(fs.join(tmp, "evil.zip"), out) })
  verify.true(e.msg.has("unsafe archive entry"))
  # nothing may have escaped the destination directory
  verify.false(fs.exists(fs.join(tmp, "evil.txt")))
  # the safe entry before it was not extracted either (all-or-nothing)
  verify.false(fs.exists(fs.join(out, "safe.txt")))
}

test "tar-slip entries are rejected" {
  py.exec(f"TMP = \"{tmp}\"")
  py.exec("""
import tarfile, io
with tarfile.open(TMP + '/evil.tgz', 'w:gz') as t:
    data = b'pwned'
    info = tarfile.TarInfo('../../evil.tar.txt')
    info.size = len(data)
    t.addfile(info, io.BytesIO(data))
""")
  let out = fs.join(tmp, "evil2-out")
  let e = verify.throws(fn () { fs.untar_gz(fs.join(tmp, "evil.tgz"), out) })
  verify.true(e.msg.has("unsafe archive entry"))
  verify.false(fs.exists(fs.join(tmp, "evil.tar.txt")))
}
