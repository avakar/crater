import os, json, errno, six, cson
from .crates import SelfCrate
from .gitcrate import GitCrate

def is_valid_crate_name(name):
    parts = name.split('/')
    return name == '' or all(part and part[0] != ' ' and part[-1] not in ('.', ' ') and '\\' not in part and ':' not in part for part in parts)

def parse_lockfile(root):
    try:
        with open(os.path.join(root, '.deps.lock'), 'r') as fin:
            d = json.load(fin)
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        d = {}

    if '' not in d:
        d[''] = {}
    else:
        if 'type' in d['']:
            raise RuntimeError('the special unnamed crate must not have a type')

    def make_crate(name, spec):
        if not is_valid_crate_name(name):
            raise RuntimeError('not a valid crate name: {}'.format(name))

        type = spec.get('type')
        if type is None:
            if name == '':
                return SelfCrate(root)
            else:
                raise RuntimeError('expected "type" attribute for crate {}'.format(path))
        elif type == 'git':
            return GitCrate(root, name, spec['commit'], spec['url'])
        else:
            raise RuntimeError('unknown dependency type: {}'.format(type))

    crates = {}
    for name, spec in six.iteritems(d):
        crate = make_crate(name, spec)
        crate._raw_deps = spec.get('dependencies', {})
        crates[name] = crate

    for crate in six.itervalues(crates):
        deps = {}
        for dep_name, target_name in six.iteritems(crate._raw_deps):
            if target_name not in crates:
                raise RuntimeError('unknown crate {} used as a target for {}:{}'.format(target_name, crate.name, dep_name))
            deps[dep_name] = crates[target_name]
        crate._deps = deps
        del crate._raw_deps

        try:
            with open(os.path.join(crate.path, 'DEPS'), 'r') as fin:
                d = cson.load(fin)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            d = {}

        crate._dep_specs = d.get('dependencies', {})
        crate._gen = d.get('gen', {})

    return _LockFile(root, crates)

class _LockFile:
    def __init__(self, root, crates):
        self._root = root
        self._crates = crates

    def crates(self):
        return six.itervalues(self._crates)

    def locate_crate(self, path):
        path = path or '.'

        rpath = os.path.normpath(os.path.relpath(path, self._root)).replace('\\', '/')
        if rpath == '..' or rpath.startswith('..'):
            raise RuntimeError('crate is outside the root: {}'.format(path))

        if rpath == '.':
            rpath = ''

        # There is a crate with path '', so this will surely find one
        for crate_rpath in sorted(self._crates):
            if crate_rpath.startswith(rpath):
                return self._crates[crate_rpath]

        assert False

    def add(self, crate):
        if crate.name in self._crates:
            raise RuntimeError('there already is a dependency in {}'.format(crate.name))
        self._crates[crate.name] = crate

    def remove(self, crate):
        for c in six.itervalues(self._crates):
            old_keys = set(dep for dep, target in c.deps() if target == crate)
            for key in old_keys:
                del c._deps[key]
        del self._crates[crate.name]

    def get_crate(self, path):
        return self._crates.get(path)

    def get_dep(self, crate_path, dep):
        crate = self.locate_crate(crate_path)
        if not crate:
            return None

        return crate.get_dep(dep)

    def status(self):
        r = {}
        def go(path, prefix):
            df = DepsFile(os.path.join(path, 'DEPS'))
            for name in df.keys():
                dep = '{}{}'.format(prefix, name)
                dep = self.deps.get(dep)
                if dep is None:
                    r[dep] = ''

        go(self.root, '')
        for dep in self.deps.values():
            go(os.path.join(self.root, dep.dir), '{}:'.format(dep.dir))

    def save(self):
        d = { crate.name: crate.serialize() for crate in six.itervalues(self._crates) }

        assert '' in d

        if len(d) == 1 and not d[''] and not os.path.isfile(self._path):
            return

        with open(os.path.join(self._root, '.deps.lock'), 'w') as fout:
            json.dump(d, fout, indent=2, sort_keys=True)

