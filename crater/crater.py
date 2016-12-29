#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno
import subprocess
import string
import random
import cson
import json
import xml.etree.ElementTree as ET

class GitKey:
    def __init__(self, spec):
        self.repo = spec['repo']

    def checkout(self, lock, target_dir):
        self._clean_env()
        if os.path.isdir(os.path.join(target_dir, '.git')):
            with open(os.devnull, 'w') as devnull:
                r = subprocess.call(['git', 'rev-parse', '--verify', '--quiet', lock], stdout=devnull, cwd=target_dir)
            if r != 0:
                subprocess.check_call(['git', 'fetch', 'origin'], cwd=target_dir)

            commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=target_dir).strip()
            if commit == lock:
                return
        else:
            try:
                os.makedirs(os.path.split(target_dir)[0])
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            subprocess.check_call(['git', 'clone', self.repo, target_dir, '--no-checkout'])

        print('checkout {} to {}'.format(lock, target_dir))
        subprocess.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=target_dir)
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', lock], cwd=target_dir)

    def update(self, lock, target_dir):
        self._clean_env()
        subprocess.check_call(['git', 'update-index', '-q', '--refresh'], cwd=target_dir)

        r = subprocess.call(['git', 'diff-index', '--quiet', 'HEAD', '--'], cwd=target_dir)
        if r != 0:
            print('error: there are changes in {}'.format(target_dir), file=sys.stderr)
            sys.exit(1)

        commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=target_dir).strip()
        if lock != commit:
            print('updating lock on {} to {}'.format(self.repo, commit))

        return commit

    def upgrade(self, target_dir):
        self._clean_env()

        if os.path.isdir(os.path.join(target_dir, '.git')):
            subprocess.check_call(['git', 'fetch', 'origin'], cwd=target_dir)
        else:
            try:
                os.makedirs(os.path.split(target_dir)[0])
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            subprocess.check_call(['git', 'clone', self.repo, target_dir, '--no-checkout'])

        commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'origin/master'], cwd=target_dir).strip()

        print('checkout {} to {}'.format(commit, target_dir))
        subprocess.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=target_dir)
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', commit], cwd=target_dir)
        return commit

    def save_key(self):
        return {
            'type': 'git',
            'repo': self.repo,
            }

    def save_lock(self, lock):
        return {
            'type': 'git',
            'repo': self.repo,
            'commit': lock,
            }

    def name_hint(self):
        r = self.repo.rsplit('/', 1)[1]
        if r.endswith('.git'):
            r = r[:-4]
        return r

    def make_lock(self, spec):
        return spec['commit']

    def detect_lock(self, dir):
        return subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=dir).strip()

    def _clean_env(self):
        # This is a workaround. For whatever reason, git calls are not reentrant.
        for key in list(os.environ):
            if key.startswith('GIT_') and key != 'GIT_SSH':
                os.unsetenv(key)
                del os.environ[key]

    def __hash__(self):
        return hash(self.repo)

    def __eq__(self, o):
        return o.__class__ == GitKey and self.repo == o.repo

_key_types = {
    'git': GitKey,
    }

def _make_key(spec):
    key_type = _key_types.get(spec['type'])
    if key_type is None:
        raise RuntimeError('unknown dependency type')
    return key_type(spec)

def _gen_msbuild(dirmap, prefix):
    templ = '''\
<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
{deps}  </PropertyGroup>
</Project>'''

    deps = []
    for name, target_dir in dirmap.items():
        deps.append('    <{prefix}{name}>{dir}</{prefix}{name}>\n'.format(prefix=prefix, name=name, dir=target_dir))
    return templ.format(deps=''.join(deps))

class Dep:
    def __init__(self, key, name, specs):
        self.key = key
        self.name = name
        self.specs = specs

class Deps:
    def __init__(self, dir):
        with open(os.path.join(dir, 'DEPS'), 'rb') as fin:
            self.specs = cson.load(fin)

        self.deps = {}

        for name, dep_spec in self.specs.get('dependencies', {}).items():
            key = _make_key(dep_spec)
            dep = Dep(key, name, dep_spec)
            self.deps[key] = dep

class Crate:
    def __init__(self, root, key):
        self.root = root
        self.key = key
        self.lock = None
        self.dir_name = None

    def checkout_dir(self):
        if self.dir_name is None:
            hint = self.key.name_hint()
            self.dir_name = self.root._alloc_name(hint)
        return os.path.join(self.root.root, self.root.deps_dir, self.dir_name)

    def update_lock(self):
        dir = self.checkout_dir()
        if dir is not None:
            self.lock = self.key.detect_lock(dir)

    def update(self):
        assert self.lock is not None
        self.lock = self.key.update(self.lock, self.checkout_dir())

class Root:
    def __init__(self, root, deps_dir):
        self.root = root
        self.deps_dir = deps_dir
        self.crates = {}
        self._used_names = set()

        try:
            with open(os.path.join(root, 'deps.lock'), 'rb') as fin:
                locks = cson.load(fin)
        except IOError:
            locks = []

        for lock in locks:
            key = _make_key(lock)
            if key in self.crates:
                raise RuntimeError('duplicate entry in deps.lock')
            crate = Crate(self, key)
            crate.lock = key.make_lock(lock)
            self.crates[key] = crate

        try:
            with open(os.path.join(root, deps_dir, 'mapping.json'), 'r') as fin:
                mj = json.load(fin)
        except:
            mj = []

        for entry in mj:
            key = _make_key(entry)
            crate = self.get(key)
            if crate.dir_name is not None:
                raise RuntimeError('duplicate entries in mapping.json')
            crate.dir_name = entry['dir']
            self._used_names.add(dir)

    def get(self, key):
        r = self.crates.get(key)
        if r is None:
            r = Crate(self, key)
            self.crates[key] = r
        return r

    def save_lock(self):
        lock_file = [crate.key.save_lock(crate.lock) for crate in self.crates.values() if crate.lock is not None]
        if lock_file:
            lock_file.sort(key=lambda e: e['repo'])
            with open(os.path.join(self.root, 'deps.lock'), 'w') as fout:
                json.dump(lock_file, fout, indent=4, sort_keys=True)

    def save_mapping(self):
        def m(crate):
            r = crate.key.save_key()
            r['dir'] = crate.dir_name
            return r

        mj = [ m(crate) for crate in self.crates.values() if crate.dir_name is not None ]
        if mj:
            mj.sort(key=lambda e: e['repo'])
            with open(os.path.join(self.deps_dir, 'mapping.json'), 'w') as fout:
                json.dump(mj, fout, indent=4, sort_keys=True)

    def _alloc_name(self, hint):
        if hint in self._used_names:
            hint = hint + '-' + random.choice(string.letters)
        while hint in self._used_names:
            hint = hint + random.choice(string.letters)
        self._used_names.add(hint)
        return hint

def _checkout(dir, deps_dir):
    root = Root(dir, deps_dir)

    q = set([dir])
    while q:
        cur = q.pop()

        try:
            deps = Deps(cur)
        except IOError:
            continue

        mapping = { 'self': os.path.abspath(cur) }
        for dep in deps.deps.values():
            crate = root.get(dep.key)
            if crate.lock is None:
                raise RuntimeError('unlocked dependency')

            dir = crate.checkout_dir()
            crate.key.checkout(crate.lock, dir)
            q.add(dir)

            mapping[dep.name] = os.path.abspath(dir)

        gen = deps.specs.get('gen', {}).get('msbuild')
        if gen is not None:
            prefix = gen.get('prop_prefix', 'dep_')
            file = gen.get('file', 'deps.props')
            content = _gen_msbuild(mapping, prefix)
            with open(os.path.join(cur, file), 'wb') as fout:
                fout.write(content)

    root.save_mapping()

def _commit(dir, deps_dir):
    root = Root(dir, deps_dir)

    for crate in root.crates.values():
        crate.update_lock()

    root.save_lock()

def _upgrade(dir, deps_dir):
    root = Root(dir, deps_dir)
    deps = Deps(dir)

    for dep in deps.deps.values():
        crate = root.get(dep.key)
        dir = crate.checkout_dir()
        crate.lock = crate.key.upgrade(dir)

    root.save_lock()
    root.save_mapping()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='.')
    ap.add_argument('--deps-dir', default='_deps')
    sp = ap.add_subparsers()
    p = sp.add_parser('checkout')
    p.set_defaults(fn=_checkout)
    p = sp.add_parser('commit')
    p.set_defaults(fn=_commit)
    p = sp.add_parser('upgrade')
    p.set_defaults(fn=_upgrade)
    args = ap.parse_args()

    fn = args.fn
    del args.fn

    return fn(**vars(args))

if __name__ == '__main__':
    sys.exit(main())
