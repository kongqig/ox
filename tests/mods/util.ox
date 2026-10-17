# helper module for the modules test
let _secret = "hidden"

fn double(x) { x * 2 }

fn shout(s) { upper(s + "!") }

export double, shout

export let version = "1.0"

fn _private() { "nope" }
