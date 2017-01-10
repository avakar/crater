import os, json, errno, six
from .crates import GitCrate, SelfCrate

def parse_lockfile(root):
    lockfile_path = os.path.join(root, '.deps.lock')
    try:
        with open(lockfile_path, 'r') as fin:
            d = json.load(fin)
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        d = {}

    crates = {}
    crates[''] = SelfCrate(root, d.get('', {}).get('links', []))
    for path, spec in six.iteritems(d):
        if path == '':
            continue
        if spec['type'] == 'git':
            crates[path] = GitCrate(root, path, spec.get('links', []), spec['commit'], spec['url'])
        else:
            raise RuntimeError('unknown dependency type: {}'.format(spec['type']))

    # resolve dependencies
    deps = {}

    lock = _LockFile(lockfile_path, crates)
    for crate in lock.crates():
        for dep in crate.deps():
            deps['{}:{}'.format(crate.name, dep.name)] = dep

    for crate in lock.crates():
        for link in crate.links:
            d = deps.get(link)
            if d is not None:
                d.crate = crate

    return lock

class _LockFile:
    def __init__(self, path, crates):
        self._path = path
        self._crates = crates

    def crates(self):
        return six.itervalues(self._crates)

    def add(self, crate):
        if crate.name in self._crates:
            raise RuntimeError('there already is a dependency in {}'.format(crate.name))
        self._crates[crate.name] = crate

    def get(self, path):
        return self._crates.get(path)

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
        assert self._crates
        if len(self._crates) <= 1 and not os.path.isfile(self._path):
            return

        d = {}
        for crate in six.itervalues(self._crates):
            if isinstance(crate, SelfCrate):
                if not crate.links:
                    continue
                cd = {}
            elif isinstance(crate, GitCrate):
                cd = { 'type': 'git', 'commit': crate.commit, 'url': crate.url }
            else:
                raise RuntimeError('unknown crate type')

            if crate.links:
                cd['links'] = crate.links
            d[crate.name] = cd

        with open(self._path, 'w') as fout:
            json.dump(d, fout, indent=2, sort_keys=True)

