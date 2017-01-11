import os, cson, errno, six, subprocess

def is_valid_dep_name(name):
    return name and ':' not in name

class CrateBase:
    def __init__(self, root, name):
        self._root = root
        self.name = name
        self.path = os.path.join(root, name)
        self._deps = {}
        self._dep_specs = {}

    def get_dep(self, dep):
        return self._deps.get(dep)

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

    def serialize(self):
        r = {}
        self._save_deps(r)
        return r

class GitCrate(CrateBase):
    def __init__(self, root, name, commit, url):
        CrateBase.__init__(self, root, name)
        self.commit = commit
        self.url = url

    def status(self):
        try:
            commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.path).strip()
        except subprocess.CalledProcessError as e:
            return 'D'

        if self.commit == commit:
            return ' '
        else:
            return 'M'

    def serialize(self):
        r = {
            'type': 'git',
            'commit': self.commit,
            'url': self.url,
            }
        self._save_deps(r)
        return r
