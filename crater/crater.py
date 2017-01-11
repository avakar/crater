#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno, shutil, stat
import subprocess
import string
import random
import cson
import json
import xml.etree.ElementTree as ET
import six

from .lockfile import parse_lockfile
from .crates import GitCrate

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
        r = self.repo.replace('\\', '/').rsplit('/', 1)[-1]
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


def _status(root):
    r = {}

    lock = parse_lockfile(root)


    for crate in lock.crates():
        unassigned = set(name for name, spec in crate.dep_specs())

        for dep_name, target in crate.deps():
            try:
                unassigned.remove(dep_name)
            except:
                pass
            full_name = '{}:{}'.format(crate.name, dep_name)
            r[full_name] = target.status()

        for dep_name in unassigned:
            full_name = '{}:{}'.format(crate.name, dep_name)
            r[full_name] = 'U'

    for name, status in sorted(r.items()):
        print('{}       {}'.format(status, name))

def _list_deps(root):
    lock = parse_lockfile(root)

    r = []
    for crate in lock.crates():
        for dep in crate.deps():
            r.append((crate.name, dep.name))

    r.sort()
    for cname, dname in r:
        print('{}:{}'.format(cname, dname))

def _assign(root, dep, crate, force):
    lock = parse_lockfile(root)
    target_crate = lock.locate_crate(crate)

    toks = dep.split(':', 1)
    if len(toks) != 2:
        toks = '', toks[0]
    cname, dname = toks

    crate = lock.locate_crate(cname)

    if dname not in crate._dep_specs:
        if not force:
            print('error: the dependency {} has no specification in the DEPS file'.format(dep), file=sys.stderr)
            return 1
        else:
            print('warning: the dependency {} has no specification in the DEPS file'.format(dep), file=sys.stderr)

    crate.set_dep(dname, target_crate)
    lock.save()

def _remove(root, target):
    lock = parse_lockfile(root)
    crate = lock.locate_crate(target)

    lock.remove(crate)
    lock.save()

def _add_git_crate(root, url, target, branch):
    if target is None:
        target = url.replace('\\', '/').rsplit('/', 1)[-1]
        if target.endswith('.git'):
            target = target[:-4]
        target = os.path.join(root, '_deps', target)

    crate_path = os.path.relpath(target, root).replace('\\', '/')

    lock = parse_lockfile(root)
    if lock.get_crate(crate_path):
        raise RuntimeError('there already is a dependency in {}'.format(target))

    cmd = ['git', 'clone', url, target]
    if branch:
        cmd.extend(('-b', branch))

    r = subprocess.call(cmd, cwd=root)
    if r != 0:
        return r

    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=os.path.join(root, target)).strip()
    except:
        def readonly_handler(rm_func, path, exc_info):
            if issubclass(exc_info[0], OSError) and exc_info[1].winerror == 5:
                os.chmod(path, stat.S_IWRITE)
                return rm_func(path)
            raise exc_info[1]
        shutil.rmtree(target, onerror=readonly_handler)
        raise

    new_crate = GitCrate(root, crate_path, commit, url)

    dep_name = os.path.split(target)[1]
    for crate in lock.crates():
        if dep_name not in crate._deps and dep_name in crate._dep_specs:
            crate.set_dep(dep_name, new_crate)

    lock.add(new_crate)
    lock.save()

    _status(root)
    return 0

def find_root(dir):
    # The root directory is the one containing the .deps.lock file.
    # If not explicitly specified by --root, try to locate search for
    # the .deps.lock file in the parents of the current directory and choose the 
    # farthest one. If there is no such directory, use current directory as the root.

    dir = os.path.abspath(dir)

    parts = []
    while True:
        dir, component = os.path.split(dir)
        if not component:
            break
        parts.append(component)

    while parts:
        if os.path.isfile(os.path.join(dir, '.deps.lock')):
            return dir
        dir = os.path.join(dir, parts.pop())

    return dir

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root')
    sp = ap.add_subparsers()
    p = sp.add_parser('checkout')
    p.set_defaults(fn=_checkout)
    p = sp.add_parser('commit')
    p.set_defaults(fn=_commit)
    p = sp.add_parser('upgrade')
    p.set_defaults(fn=_upgrade)

    p = sp.add_parser('add-git')
    p.add_argument('--branch', '-b')
    p.add_argument('url')
    p.add_argument('target', nargs='?')
    p.set_defaults(fn=_add_git_crate)

    for cmd in ('rm', 'remove'):
        p = sp.add_parser(cmd)
        p.add_argument('target', default='.')
        p.set_defaults(fn=_remove)

    p = sp.add_parser('list-deps')
    p.set_defaults(fn=_list_deps)

    p = sp.add_parser('assign')
    p.add_argument('--force', '-f', action='store_true')
    p.add_argument('dep')
    p.add_argument('crate')
    p.set_defaults(fn=_assign)

    p = sp.add_parser('status')
    p.set_defaults(fn=_status)

    args = ap.parse_args()

    fn = args.fn
    del args.fn

    if not args.root:
        args.root = find_root('.')

    return fn(**vars(args))

if __name__ == '__main__':
    sys.exit(main())
