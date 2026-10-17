"""math — numbers, randomness and simple numeric helpers."""
import math as _math
import random as _random

from ..values import Duration, NativeModule, builtin


def _min(*args):
    if len(args) == 1 and isinstance(args[0], list):
        args = args[0]
    return min(args)


def _max(*args):
    if len(args) == 1 and isinstance(args[0], list):
        args = args[0]
    return max(args)


def _rand(n=None):
    if n is None:
        return _random.random()
    return _random.randint(0, int(n) - 1)


def _choice(lst):
    if not lst:
        raise ValueError("choice() on an empty list")
    return _random.choice(lst)


def _shuffle(lst):
    out = list(lst)
    _random.shuffle(out)
    return out


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _even(n):
    return int(n) % 2 == 0


def _odd(n):
    return int(n) % 2 == 1


def build():
    return NativeModule("math", {
        "pi": _math.pi,
        "e": _math.e,
        "abs": builtin("abs")(abs),
        "floor": builtin("floor")(_math.floor),
        "ceil": builtin("ceil")(_math.ceil),
        "round": builtin("round")(round),
        "sqrt": builtin("sqrt")(_math.sqrt),
        "pow": builtin("pow")(_math.pow),
        "exp": builtin("exp")(_math.exp),
        "log": builtin("log")(_math.log),
        "log2": builtin("log2")(_math.log2),
        "log10": builtin("log10")(_math.log10),
        "sin": builtin("sin")(_math.sin),
        "cos": builtin("cos")(_math.cos),
        "tan": builtin("tan")(_math.tan),
        "atan": builtin("atan")(_math.atan),
        "atan2": builtin("atan2")(_math.atan2),
        "min": builtin("min")(_min),
        "max": builtin("max")(_max),
        "sum": builtin("sum")(lambda l: sum(x for x in l
                                            if isinstance(x, (int, float)))),
        "rand": builtin("rand")(_rand),
        "randf": builtin("randf")(_random.random),
        "choice": builtin("choice")(_choice),
        "shuffle": builtin("shuffle")(_shuffle),
        "clamp": builtin("clamp")(_clamp),
        "even": builtin("even")(_even),
        "odd": builtin("odd")(_odd),
        "gcd": builtin("gcd")(_math.gcd),
    })
