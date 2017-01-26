#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno, shutil, stat
import subprocess
import six

from .lockfile import parse_lockfile
from .gitcrate import GitCrate, GitDepSpec
from .tarcrate import TarCrate
from .gen import gen

def _checkout(lock):
    for crate in lock.crates():
        crate.checkout()
        crate.reload_deps()

        mapping = { 'self': os.path.abspath(crate.path) }
        for dep, target in crate.deps():
            mapping[dep] = os.path.abspath(target.path)

        gen(crate.path, mapping, crate._gen)
    return 0

def _commit(lock):
    for crate in lock.crates():
        crate.update()
    lock.save()
    return 0

def _status(lock):
    r = {}

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
    return 0

def _upgrade(lock, depid, target_dir):
    crates_to_upgrade = []

    def find_reverse_deps(crate):
        r = []
        for src in lock.crates():
            for dep_name, dest in src.deps():
                if dest == crate:
                    r.append((src, dep_name))
        return r

    if depid is None:
        for crate in lock.crates():
            crates_to_upgrade.append((crate, find_reverse_deps(crate)))
        # TODO: unchecked deps
    else:
        crate, dep_name = lock.parse_depid(depid)
        target_crate = crate.get_dep(dep_name)

        if target_crate is None:
            crates_to_upgrade.append((None, [(crate, dep_name)]))
        else:
            crates_to_upgrade.append((target_crate, find_reverse_deps(target_crate)))

    for crate, dep_list in crates_to_upgrade:
        assert dep_list
        dep_crate, dep_name = dep_list[0]
        dep_spec = dep_crate.get_dep_spec(dep_name)

        for dep_crate, dep_name in dep_list[1:]:
            dep_spec = join_dep_specs(dep_spec, dep_crate.get_dep_spec(dep_name))

        if crate is None:
            if target_dir is None:
                target_dir = lock.new_unique_crate_name(dep_spec)
            new_crate = lock.init_crate(dep_spec, target_dir)

            for dep_crate, dep_name in dep_list:
                dep_crate.set_dep(dep_name, new_crate)
        else:
            crate.upgrade(dep_spec)

    lock.save()

def _list_deps(lock):
    r = []
    for crate in lock.crates():
        for dep in crate.deps():
            r.append((crate.name, dep.name))

    r.sort()
    for cname, dname in r:
        print('{}:{}'.format(cname, dname))
    return 0

def _assign(lock, dep, crate, force):
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
    return 0

def _remove(lock, target):
    crate = lock.locate_crate(target)

    lock.remove(crate)
    lock.save()

def _add_git_crate(lock, url, target, branch, quiet):
    dep_spec = GitDepSpec(url, [branch or 'master'])

    if target is None:
        crate_name = lock.new_unique_crate_name(dep_spec)
        target = crate_name
    else:
        crate_name = lock.crate_name_from_path(target)

    new_crate = lock.init_crate(dep_spec, crate_name)

    dep_name = os.path.split(target)[1]
    for crate in lock.crates():
        if dep_name not in crate._deps and dep_name in crate._dep_specs:
            crate.set_dep(dep_name, new_crate)

    lock.save()

    _status(lock)
    return 0

def _add_tar_crate(lock, url, target, subdir, exclude):
    if target is None:
        target = url.replace('\\', '/').rsplit('/', 1)[-1]
        target = target.split('.', 1)[0]
        target = os.path.join(lock.root(), '_deps', target)

    crate_path = os.path.relpath(target, lock.root()).replace('\\', '/')

    new_crate = TarCrate(lock.root(), crate_path, hash=None, url=url, subdir=subdir, exclude=exclude)
    new_crate.checkout()
    lock.add(new_crate)
    lock.save()
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

def _main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root')
    sp = ap.add_subparsers()

    for cmd in ('checkout', 'co'):
        p = sp.add_parser(cmd)
        p.set_defaults(fn=_checkout)

    for cmd in ('commit', 'ci'):
        p = sp.add_parser(cmd)
        p.set_defaults(fn=_commit)

    p = sp.add_parser('add-git')
    p.add_argument('--branch', '-b')
    p.add_argument('--quiet', '-q', action='store_true')
    p.add_argument('url')
    p.add_argument('target', nargs='?')
    p.set_defaults(fn=_add_git_crate)

    p = sp.add_parser('add-tar')
    p.add_argument('--subdir')
    p.add_argument('--exclude', '-X', action="append")
    p.add_argument('url')
    p.add_argument('target', nargs='?')
    p.set_defaults(fn=_add_tar_crate)

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

    for cmd in ('st', 'status'):
        p = sp.add_parser(cmd)
        p.set_defaults(fn=_status)

    p = sp.add_parser('upgrade')
    p.add_argument('depid', nargs='?')
    p.add_argument('target_dir', nargs='?')
    p.set_defaults(fn=_upgrade)

    args = ap.parse_args(argv)

    fn = args.fn
    del args.fn

    root = args.root or find_root('.')
    del args.root

    lock = parse_lockfile(root)

    return fn(lock=lock, **vars(args))

def main():
    return _main(sys.argv[1:])

if __name__ == '__main__':
    sys.exit(main())
