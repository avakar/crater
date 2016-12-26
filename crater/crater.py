#!/usr/bin/env python

import argparse
import os, errno
import subprocess
import cson
import xml.etree.ElementTree as ET

class GitLock:
    def __init__(self, repo, commit):
        self.repo = repo
        self.commit = commit

    def checkout(self, target_dir):
        print 'checkout {} to {}'.format(self.commit, target_dir)
        subprocess.check_call(['git', 'clone', self.repo, target_dir, '--no-checkout'])
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', self.commit], cwd=target_dir)

class GitKey:
    def __init__(self, repo):
        self.repo = repo

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

    r = []
    for name, target_dir in dirmap.items():
        r.append('    <{prefix}{name}>{dir}</{prefix}{name}>\n'.format(prefix=prefix, name=name, dir=target_dir))
    return templ.format(deps=''.join(r))

def _checkout(dir, deps_dir):
    try:
        with open(os.path.join(dir, 'deps.lock'), 'rb') as fin:
            lock = cson.load(fin)
    except IOError:
        return 0

    try:
        os.makedirs(deps_dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    entries = {}
    for entry in lock:
        key = _make_key(entry)
        if key in entries:
            raise RuntimeError('duplicate entry in deps.lock')
        entries[key] = GitLock(entry['repo'], entry['commit'])

    for top, dirs, files in os.walk(dir):
        if 'DEPS' in files:
            with open(os.path.join(top, 'DEPS'), 'rb') as fin:
                specs = cson.load(fin)

            packages = specs['packages']

            mapping = {}
            for pack in packages:
                dep = packages[pack]
                key = _make_key(dep)
                if key not in entries:
                    raise RuntimeError('unlocked dependency')
                lock = entries[key]

                target_dir = os.path.join(deps_dir, pack)
                mapping[pack] = target_dir
                lock.checkout(target_dir)

            gen = specs.get('gen', {}).get('msbuild')
            if gen is not None:
                prefix = gen.get('prop_prefix', 'dep_')
                file = gen.get('file', 'deps.props')
                content = _gen_msbuild(mapping, prefix)
                with open(file, 'wb') as fout:
                    fout.write(content)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='.')
    ap.add_argument('--deps-dir', default='_deps')
    sp = ap.add_subparsers()
    p = sp.add_parser('checkout')
    p.set_defaults(fn=_checkout)
    args = ap.parse_args()

    fn = args.fn
    del args.fn

    return fn(**vars(args))

if __name__ == '__main__':
    sys.exit(main())
