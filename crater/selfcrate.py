import os

class SelfDepSpec:
    def join(self, o):
        if not isinstance(o, SelfDepSpec):
            return None
        return self

class SelfRemote:
    def __eq__(self, rhs):
        return isinstance(rhs, SelfRemote)

    def __hash__(self):
        return hash(None)

class SelfVersion:
    def __eq__(self, rhs):
        return isinstance(rhs, SelfVersion)

    def __hash__(self):
        return hash(None)

class SelfHandler:
    def fetch(self, path, log):
        pass

    def versions(self, path, dep_spec, log):
        return [SelfVersion()]

    def checkout(self, remote, version, path, log):
        pass

    def save_lock(self, remote, ver):
        return {}

    def save(self):
        return {}

    def get_deps_file(self, path, ver, log):
        try:
            with open(os.path.join(path, 'DEPS'), 'r') as fin:
                return fin.read()
        except IOError:
            return '{}'

    def status(self, path, log):
        return SelfVersion(), False

    def load_lock(self, spec):
        return SelfRemote(), SelfVersion()

    def empty_dep_spec(self):
        return SelfDepSpec()

self_handler = SelfHandler()
