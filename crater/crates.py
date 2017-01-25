import os, cson, errno, six, subprocess

def is_valid_dep_name(name):
    return name and ':' not in name

class CrateBase:
    def __init__(self, root, name):
        self._root = root
        self.name = name
        self.path = os.path.join(root, name)
        self._gen = {}
        self._deps = {}
        self._dep_specs = {}

    def reload_deps(self):
        try:
            with open(os.path.join(self.path, 'DEPS'), 'r') as fin:
                d = cson.load(fin)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            d = {}

        self._dep_specs = d.get('dependencies', {})
        self._gen = d.get('gen', {})

    def get_dep(self, dep):
        return self._deps.get(dep)

    def get_dep_spec(self, dep_name):
        return self._dep_specs.get(dep_name)

    def deps(self):
        return six.iteritems(self._deps)

    def dep_specs(self):
        return six.iteritems(self._dep_specs)

    def set_dep(self, name, target_crate):
        if not is_valid_dep_name(name):
            raise RuntimeError('invalid name for a dependency'.format(':'))
        self._deps[name] = target_crate

    def status(self):
        return '?'

    def _save_deps(self, d):
        if self._deps:
            d['dependencies'] = { name: crate.name for name, crate in six.iteritems(self._deps) }

class SelfCrate(CrateBase):
    def __init__(self, root):
        CrateBase.__init__(self, root, '')

    def save(self):
        r = {}
        self._save_deps(r)
        return r

    def update(self):
        pass

    def checkout(self):
        pass
