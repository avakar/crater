#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno, shutil, stat
import subprocess
import six

from .lockfile import parse_lockfile
from .gitcrate import GitCrate
from .gen import gen

def _checkout(root):
    lock = parse_lockfile(root)

    for crate in lock.crates():
        crate.checkout()

        mapping = { 'self': os.path.abspath(crate.path) }
        for dep, target in crate.deps():
            mapping[dep] = os.path.abspath(target.path)

        gen(crate.path, mapping, crate._gen)

def _commit(root):
    lock = parse_lockfile(root)

    for crate in lock.crates():
        crate.commit()

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
