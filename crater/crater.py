#!/usr/bin/env python

import argparse
import sys
import os, errno
import subprocess
import string
import random
import cson
import json
import xml.etree.ElementTree as ET

class GitLock:
    def __init__(self, repo, commit):
        self.repo = repo
        self.commit = commit

    def checkout(self, target_dir):
        print 'checkout {} to {}'.format(self.commit, target_dir)

        if os.path.isdir(os.path.join(target_dir, '.git')):
            with open(os.devnull, 'w') as devnull:
                r = subprocess.call(['git', 'rev-parse', '--verify', '--quiet', self.commit], stdout=devnull, cwd=target_dir)
            if r != 0:
                subprocess.check_call(['git', 'fetch', 'origin'], cwd=target_dir)
        else:
            subprocess.check_call(['git', 'clone', self.repo, target_dir, '--no-checkout'])
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', self.commit], cwd=target_dir)

    def update(self, target_dir):
        self.commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=target_dir).strip()

    def to_json(self):
        return {
            'type': 'git',
            'repo': self.repo,
            'commit': self.commit,
            }

class GitKey:
    def __init__(self, repo):
        self.repo = repo

    def to_json(self):
        return {
            'type': 'git',
            'repo': self.repo,
            }

    def name_hint(self):
        r = self.repo.rsplit('/', 1)[1]
        if r.endswith('.git'):
            r = r[:-4]
        return r

    def make_lock(self, spec):
        return GitLock(self.repo, spec['commit'])

    def __hash__(self):
        return hash(self.repo)

    def __eq__(self, o):
        return o.__class__ == GitKey and self.repo == o.repo

def _make_key(spec):
    if spec['type'] != 'git':
        raise RuntimeError('unknown dependency type')
    return GitKey(spec['repo'])

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

        for name, dep_spec in self.specs.get('packages', {}).items():
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
        assert self.lock is not None

        if self.dir_name is None:
            hint = self.lock.name_hint()
            self.dir_name = self.root._alloc_name(hint)
        return os.path.join(self.root.root, self.root.deps_dir, self.dir_name)

    def update(self):
        assert self.lock is not None
        self.lock.update(self.checkout_dir())

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
            crate.lock = GitLock(lock['repo'], lock['commit'])
            self.crates[key] = crate

        try:
            with open(os.path.join(root, deps_dir, 'mapping.json'), 'r') as fin:
                mj = json.load(fin)
        except:
            mj = []

        for key, dir in mj:
            key = _make_key(key)
            crate = self.get(key)
            if crate.dir_name is not None:
                raise RuntimeError('duplicate entries in mapping.json')
            crate.dir_name = dir
            self._used_names.add(dir)

    def get(self, key):
        r = self.crates.get(key)
        if r is None:
            r = Crate(self, key)
            self.crates[key] = r
        return r

    def _alloc_name(self, hint):
        if hint in self._used_names:
            hint = hint + '-' + random.choice(string.letters)
        while hint in self._used_names:
            hint = hint + random.choice(string.letters)
        self._used_names.add(hint)
        return hint


def _checkout(dir, deps_dir):
    root = Root(dir, deps_dir)

    try:
        os.makedirs(os.path.join(dir, deps_dir))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    q = set(['.'])
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
            crate.lock.checkout(dir)
            q.add(dir)

            mapping[dep.name] = os.path.abspath(dir)

        gen = deps.specs.get('gen', {}).get('msbuild')
        if gen is not None:
            prefix = gen.get('prop_prefix', 'dep_')
            file = gen.get('file', 'deps.props')
            content = _gen_msbuild(mapping, prefix)
            with open(os.path.join(cur, file), 'wb') as fout:
                fout.write(content)

    mj = [ (crate.key.to_json(), crate.dir_name) for crate in root.crates.values() if crate.dir_name is not None ]
    with open(os.path.join(deps_dir, 'mapping.json'), 'w') as fout:
        json.dump(mj, fout)

def _commit(dir, deps_dir):
    root = Root(dir, deps_dir)

    for crate in root.crates.values():
        if crate.lock:
            crate.update();

    lock_file = [crate.lock.to_json() for crate in root.crates.values() if crate.lock is not None]
    lock_file.sort(key=lambda e: e['repo'])
    with open(os.path.join(dir, 'deps.lock'), 'w') as fout:
        cson.dump(lock_file, fout, indent=4, sort_keys=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='.')
    ap.add_argument('--deps-dir', default='_deps')
    sp = ap.add_subparsers()
    p = sp.add_parser('checkout')
    p.set_defaults(fn=_checkout)
    p = sp.add_parser('commit')
    p.set_defaults(fn=_commit)
    args = ap.parse_args()

    fn = args.fn
    del args.fn

    return fn(**vars(args))

if __name__ == '__main__':
    sys.exit(main())
