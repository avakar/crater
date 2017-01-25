import os, json, errno, six, cson, random, string
from .crates import SelfCrate
from .gitcrate import GitCrate
from .tarcrate import TarCrate

_crate_types = {
    'git': GitCrate,
    'tar': TarCrate,
    }

def is_valid_crate_name(name):
    parts = name.split('/')
    return name == '' or all(part and part[0] != ' ' and part[-1] not in ('.', ' ') and '\\' not in part and ':' not in part for part in parts)

def init_crate(lock, crate_name, dep_spec):
    type = _crate_types.get(dep_spec.get('type'))
    if type is None:
        raise RuntimeError('unknown dependency type: {}'.format(type))
    return type.init(lock.root(), crate_name, dep_spec)

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
        else:
            cls = _crate_types.get(type)
            if cls is None:
                raise RuntimeError('unknown dependency type: {}'.format(type))
            return cls.load(root, name, spec)

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

        crate.reload_deps()

    return _LockFile(root, crates)

class _LockFile:
    def __init__(self, root, crates):
        self._root = root
        self._crates = crates

    def root(self):
        return self._root

    def crates(self):
        return six.itervalues(self._crates)

    def locate_crate(self, path):
        rpath = self.crate_name_from_path(path)

        # There is a crate with path '', so this will surely find one
        for crate_rpath in sorted(self._crates):
            if crate_rpath.startswith(rpath):
                return self._crates[crate_rpath]

        assert False

    def crate_name_from_path(self, path):
        path = path or '.'

        rpath = os.path.normpath(os.path.relpath(path, self._root)).replace('\\', '/')
        if rpath == '..' or rpath.startswith('..'):
            raise RuntimeError('crate is outside the root: {}'.format(path))
        if rpath == '.':
            rpath = ''

        return rpath

    def new_unique_crate_name(self, dep_spec, deps_dir=None):
        typeid = dep_spec.get('type')
        type = _crate_types.get(typeid)
        if type is None:
            raise RuntimeError('unknown crate type: {}'.format(typeid))

        hint = type.name_hint(dep_spec)
        deps_dir = self.guess_deps_dir(deps_dir)
        target_dir = os.path.join(deps_dir, hint)
        if os.path.exists(target_dir):
            target_dir += '-'
            target_dir += random.choice(string.ascii_lowercase)
            while os.path.exists(target_dir):
                target_dir += random.choice(string.ascii_lowercase)

        return self.crate_name_from_path(target_dir)

    def guess_deps_dir(self, deps_dir=None):
        if deps_dir is not None:
            return deps_dir

        common_prefix = None
        for crate_name in self._crates:
            if not crate_name:
                continue

            if common_prefix is None:
                common_prefix = crate_name.split('/')[:-1]
            else:
                components = crate_name.split('/')
                for i, (l, r) in enumerate(zip(common_prefix, components)):
                    if l != r:
                        common_prefix = common_prefix[:i]
                        break

        if not common_prefix:
            return os.path.join(self._root, '_deps')

        return os.path.join(self._root, *common_prefix)

    def init_crate(self, dep_spec, crate_name):
        typeid = dep_spec.get('type')
        type = _crate_types.get(typeid)
        if type is None:
            raise RuntimeError('unknown crate type: {}'.format(typeid))

        new_crate = type.init(self.root(), crate_name, dep_spec)
        self.add(new_crate)
        return new_crate

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
        d = { crate.name: crate.save() for crate in six.itervalues(self._crates) }

        assert '' in d

        path = os.path.join(self._root, '.deps.lock')
        if len(d) == 1 and not d[''] and not os.path.isfile(path):
            return

        with open(path, 'w') as fout:
            json.dump(d, fout, indent=2, sort_keys=True)

