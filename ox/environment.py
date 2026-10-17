"""Lexical environments (scope chains) for the ox interpreter."""


class Env:
    __slots__ = ("values", "mutables", "parent", "name")

    def __init__(self, parent=None, name=None):
        self.values = {}
        self.mutables = set()  # names declared with `var` (or parameters)
        self.parent = parent
        self.name = name

    def define(self, name, value, mutable=False):
        self.values[name] = value
        if mutable or name == "_":
            self.mutables.add(name)

    def has_here(self, name):
        return name in self.values

    def find_env(self, name):
        e = self
        while e is not None:
            if name in e.values:
                return e
            e = e.parent
        return None

    def get(self, name):
        e = self.find_env(name)
        if e is None:
            raise KeyError(name)
        return e.values[name]

    def assign(self, name, value):
        e = self.find_env(name)
        if e is None:
            return False
        e.values[name] = value
        return True

    def is_mutable(self, name):
        e = self.find_env(name)
        return e is not None and (name in e.mutables or name == "_")

    def root(self):
        e = self
        while e.parent is not None:
            e = e.parent
        return e

    def own_names(self):
        return list(self.values.keys())
