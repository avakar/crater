#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import os, errno, shutil, stat
import subprocess
import six

from .log import Log
from .lockfile import parse_lockfile
from .gitcrate import GitRemote, GitDepSpec
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

    dir = lock.guess_deps_dir(dir)

    remotes = {}
    for crate in lock.crates():
        remotes.setdefault(crate.remote(), set()).add(crate)

    def make_crate(remote, dep_spec):
        target = remotes.get(remote)
        if target is None:
            name = lock.new_unique_crate_name(remote, dir)
            new_crate = lock.init_crate(remote, dep_spec, name)
            remotes[remote] = new_crate
            return new_crate
        elif len(target) == 1:
            cur_target = next(iter(target))
            cur.set_dep(dep_name, cur_target)
            return cut_target
        else:
            # Can't associate, skip this dep
            # XXX write a warning to the log
            return None

    targets = {}

    def lock_one(unlocked, locked):
        if not unlocked:
            return locked

        locked = dict(locked)
        unlocked = dict(unlocked)

        c = next(iter(unlocked))
        dep_spec = unlocked[c]
        del unlocked[c]

        for ver in c.versions(dep_spec):
            locked[c] = ver

            new_dep_specs = c.get_dep_specs(ver)
            for dep_name, (remote, ds) in six.iteritems(new_dep_specs):
                tgt = c.get_dep(dep_name)
                if tgt is None:
                    tgt = make_crate(remote, ds)
                    if tgt is None:
                        # Can't associate, skip this dep
                        # XXX write a warning to the log
                        continue

                targets[c, dep_name] = tgt
                if tgt in locked:
                    if not ds.is_compatible_with(locked[tgt]):
                        return
                elif tgt in unlocked:
                    ds = unlocked[tgt].join(ds)
                    if ds is None:
                        return
                    unlocked[tgt] = ds
                else:
                    unlocked[tgt] = ds

            r = lock_one(unlocked, locked)
            if r is not None:
                return r

    self_crate = lock.get_crate('')
    unlocked_crates = { self_crate : self_crate.empty_dep_spec() }
    r = lock_one(unlocked_crates, locked={})

    for (c, dep_name), tgt in six.iteritems(targets):
        c.set_dep(dep_name, tgt)

    for c, ver in six.iteritems(r):
        c.checkout(ver)

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
    remote = GitRemote(url)
    dep_spec = GitDepSpec([branch or 'master'])

    if target is None:
        crate_name = lock.new_unique_crate_name(remote)
        target = crate_name
    else:
        crate_name = lock.crate_name_from_path(target)

    new_crate = lock.init_crate(remote, dep_spec, crate_name)
    new_crate.checkout()

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
