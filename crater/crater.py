#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno, shutil, stat
import subprocess
import six

from .log import Log
from .lockfile import parse_lockfile
from .gitcrate import GitCrate, GitDepSpec
from .tarcrate import TarCrate
from .gen import gen

def _init(lock):
    if not lock.is_empty():
        lock.log.error('the crate is already initialized')
        return 1

    lock.save(force=True)
    return 0

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
    r = []

    stati = {}

    for crate in lock.crates():
        assigned = set()

        for dep_name, target in crate.deps():
            assigned.add(dep_name)

            if target not in stati:
                stati[target] = target.status()

            full_name = '{}:{}'.format(crate.name, dep_name)
            r.append((full_name, stati[target], os.path.relpath(target.path)))

        for dep_name in (name for name, spec in crate.dep_specs() if name not in assigned):
            full_name = '{}:{}'.format(crate.name, dep_name)
            r.append((full_name, 'U ', ''))

    if not r:
        return 0

    r.sort(key=lambda r: (r[2], r[1]))

    max_name_len = max(len(name) for name, status, target in r)
    templ = '{{}}      {{:<{}s}}'.format(max_name_len)

    last_target = ''
    for name, status, target in r:
        if target == last_target:
            lock.log.write(templ.format(status, name) + '\n')
        else:
            lock.log.write(templ.format(status, name) + '    {}\n'.format(target))
            last_target = target

    return 0

def _upgrade(lock, depid, target_dir, dir):

    errors = []

    dir = lock.guess_deps_dir(dir)

    try:
        done = False
        while not done:
            done = True

            new_crates = []
            for src in lock.crates():
                for dep_name, dep_spec in src.dep_specs():
                    if src.get_dep(dep_name) is not None:
                        continue

                    compat_crates = set(crate for crate in lock.crates() if crate.self_spec().join(dep_spec) is not None)
                    if len(compat_crates) == 1:
                        src.set_dep(dep_name, compat_crates.pop())
                    elif len(compat_crates) > 1:
                        errors.append((src, dep_name))
                        continue

                    for idx, (ds, dep_list) in enumerate(new_crates):
                        new_spec = ds.join(dep_spec)
                        if new_spec is not None:
                            dep_list.append((src, dep_name))
                            new_crates[idx] = new_spec, dep_list
                            break
                    else:
                        new_crates.append((dep_spec, [(src, dep_name)]))

            if new_crates:
                if dir is None:
                    lock.log.error('can\'t guess the dependency directory, use --dir')
                    return 1
                else:
                    done = False
                    for dep_spec, dep_list in new_crates:
                        name = lock.new_unique_crate_name(dep_spec, dir)
                        new_crate = lock.init_crate(dep_spec, name)
                        for src, dep in dep_list:
                            src.set_dep(dep, new_crate)
    finally:
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

def _main(argv, log):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root')
    sp = ap.add_subparsers()

    p = sp.add_parser('init')
    p.set_defaults(fn=_init)

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
    p.add_argument('--dir')
    p.add_argument('depid', nargs='?')
    p.add_argument('target_dir', nargs='?')
    p.set_defaults(fn=_upgrade)

    args = ap.parse_args(argv)

    fn = args.fn
    del args.fn

    root = args.root or find_root('.')
    del args.root

    lock = parse_lockfile(root, log)

    return fn(lock=lock, **vars(args))

def main():
    return _main(sys.argv[1:], Log(sys.stderr))

if __name__ == '__main__':
    sys.exit(main())
