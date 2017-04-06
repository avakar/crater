import os, json, errno, six, cson, random, string
from .selfcrate import self_handler
from .gitcrate import git_handler

_crate_types = {
    'git': git_handler,
    }

def is_valid_dep_name(name):
    return name and ':' not in name

def is_valid_crate_name(name):
    parts = name.split('/')
    return name == '' or all(part and part[0] != ' ' and part[-1] not in ('.', ' ') and '\\' not in part and ':' not in part for part in parts)

def parse_lockfile(root, log):
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

    crates = {}
    for name, spec in six.iteritems(d):
        if not is_valid_crate_name(name):
            raise RuntimeError('not a valid crate name: {}'.format(name))

        type = spec.get('type')
        if type is None:
            if name != '':
                raise RuntimeError('expected "type" attribute for crate {}'.format(path))
            handler = self_handler
        else:
            handler = _crate_types.get(type)
            if handler is None:
                raise RuntimeError('unknown dependency type: {}'.format(type))
        remote, ver = handler.load_lock(spec)

        crate = Crate(root, name, handler, remote, ver, log)
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

    return _LockFile(root, crates, log)

class Crate:
    def __init__(self, root, name, handler, remote, ver, log):
        self.name = name
        self.path = os.path.join(root, name)

        self._log = log
        self._handler = handler
        self._remote = remote
        self._version = ver
        self._root = root
        self._gen = None
        self._deps = {}
        self._dep_specs = {}

    def fetch(self):
        self._handler.fetch(self.path, self._log)

    def versions(self, dep_spec):
        return self._handler.versions(self.path, dep_spec, self._log)

    def gen_stmts(self):
        if self._gen is None:
            self.reload_deps()
        return self._gen

    def reload_deps(self):
        try:
            with open(os.path.join(self.path, 'DEPS'), 'r') as fin:
                d = cson.load(fin)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            d = {}
            self._gen = {}
        else:
            gen = d.get('gen')
            if gen is None:
                self._gen = { 'cmake': {} }
            else:
                self._gen = gen

        self._dep_specs = {}
        for dep_name, spec in six.iteritems(d.get('dependencies', {})):
            handler = _crate_types[spec['type']]
            self._dep_specs[dep_name] = handler.load_depspec(spec)

    def current_version(self):
        return self._version

    def get_dep_specs(self, ver):
        d = self._handler.get_deps_file(self.path, ver, self._log)
        d = cson.loads(d)

        r = {}
        for dep_name, spec in six.iteritems(d.get('dependencies', {})):
            handler = _crate_types[spec['type']]
            r[dep_name] = handler.load_depspec(spec)

        return r

    def is_self_crate(self):
        return self._handler == self_handler

    def is_compatible_ver(self, ver, ds):
        return self._handler.is_compatible_ver(self.path, self._log, ver, ds)

    def checkout(self, ver=None):
        if ver is None:
            ver = self._version
        self._handler.checkout(self._remote, ver, self.path, self._log)
        self._version = ver

    def update(self):
        new_ver, dirty = self._handler.status(self.path, self._log)
        if new_ver is None:
            raise RuntimeError('the crate is corrupted somehow: {}'.format(self.path))
        self._version = new_ver

    def remote(self):
        return self._remote

    def get_dep(self, dep):
        return self._deps.get(dep)

    def get_dep_spec(self, dep_name):
        return self._dep_specs.get(dep_name)

    def empty_dep_spec(self):
        return self._handler.empty_dep_spec()

    def deps(self):
        return six.iteritems(self._deps)

    def dep_specs(self):
        return six.iteritems(self._dep_specs)

    def set_dep(self, name, target_crate):
        if not is_valid_dep_name(name):
            raise RuntimeError('invalid name for a dependency'.format(':'))
        self._deps[name] = target_crate

    def status(self):
        if not os.path.isdir(self.path):
            return 'D '

        new_ver, dirty = self._handler.status(self.path, self._log)
        if new_ver is None:
            return '! '

        return '{}{}'.format(' ' if self._version == new_ver else 'M', '*' if dirty else ' ')

    def save(self):
        d = self._handler.save_lock(self._remote, self._version)
        if self._deps:
            d['dependencies'] = { name: crate.name for name, crate in six.iteritems(self._deps) }
        return d

class _LockFile:
    def __init__(self, root, crates, log):
        self._root = root
        self._crates = crates
        self.log = log

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

    def new_unique_crate_name(self, remote, deps_dir=None):
        hint = remote.name_hint()
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

    def init_crate(self, remote, dep_spec, crate_name):
        path = os.path.join(self._root, crate_name)
        handler, ver = dep_spec.init(path, remote, self.log)

        crate = Crate(self._root, crate_name, handler, remote, ver, self.log)
        self.add(crate)
        return crate

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

    def is_empty(self):
        return len(self._crates) == 1 and not self._crates['']._deps

    def save(self, force=False):
        d = { crate.name: crate.save() for crate in six.itervalues(self._crates) }

        assert '' in d

        path = os.path.join(self._root, '.deps.lock')
        if not force and self.is_empty() and not os.path.isfile(path):
            return

        with open(path, 'w') as fout:
            json.dump(d, fout, indent=2, sort_keys=True)

