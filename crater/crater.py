#!/usr/bin/env python

import sys, argparse, os.path, subprocess, platform, errno
import pytoml as toml
import template_msvc12
import template_makefile
import template_qt

templates = {
    'msvc12': template_msvc12.gen,
    'makefile': template_makefile.gen,
    'qt': template_qt.gen,
    }

class CraterError(Exception):
    e_no_cratefile = 1

    msgs = {
        e_no_cratefile: 'no Cratefile found',
        }

    def __init__(self, err):
        msg = CraterError.msgs.get(err, 'unknown error')
        super(CraterError, self).__init__(msg)
        self.err = err

class Crate:
    def __init__(self, src, scope):
        self.src = src
        self.scope = scope
        self.name = self.src['name']
        self.input_dir = scope.input_dir

    def resolve_ref(self, name):
        return self.scope.resolve_ref(name)

    def get(self, key, default=None):
        return self.src.get(key, default)

    def __contains__(self, key):
        return key in self.src

    def __setitem__(self, key, value):
        self.src[key] = value

    def __getitem__(self, key):
        return self.src[key]

    def __str__(self):
        return '{}#{}'.format(self.scope.crate_def, self.name)

    def __repr__(self):
        return 'Crate({})'.format(self)

class Scope:
    def __init__(self, cache, crate_def, input_dir, crates):
        self.cache = cache
        self.crate_def = crate_def
        self.input_dir = input_dir
        self.crates = [Crate(c, self) for c in crates]
        self.map = { crate.name: crate for crate in self.crates }

    def resolve_ref(self, name):
        if name in self.map:
            resolved = self.cache.resolve_crate(self.map[name])
            self.map[name] = resolved
            return resolved
        return self.cache.resolve_ref(name)

class CrateCache:
    def __init__(self, ref_overrides, output_dir):
        self.ref_overrides = ref_overrides
        self.output_dir = output_dir
        self.deps_dir = os.path.join(output_dir, 'deps')
        self.externs = {}
        self.scopes = {}

    def _load_scope(self, crate_def):
        if crate_def in self.scopes:
            return self.scopes[crate_def]

        if os.path.isdir(crate_def):
            crate_def = os.path.join(crate_def, 'Cratefile')

        crate_fname = crate_def

        try:
            with open(crate_fname, 'r') as fin:
                cratefile = toml.load(fin)
                input_dir = os.path.split(crate_def)[0]
        except IOError, e:
            if e.errno == errno.ENOENT:
                raise CraterError(CraterError.e_no_cratefile)
            raise

        def match_target(target):
            return target == platform.system().lower()

        crates = []
        for crate in cratefile.get('crate', []):
            parts = [tg_def for tg_name, tg_def in crate.get('target', {}).iteritems() if match_target(tg_name)]

            for part in parts:
                for k, v in part.iteritems():
                    if k not in crate:
                        crate[k] = v
                        continue

                    if isinstance(v, list):
                        crate[k].extend(v)
                    elif isinstance(v, dict):
                        crate[k].update(v)
                    else:
                        crate[k] = v

            crates.append(crate)

        scope = Scope(self, crate_def, input_dir, crates)
        scope.fname = crate_fname
        self.scopes[crate_def] = scope
        return scope

    def resolve_crate(self, crate):
        if crate.get('type', 'extern') != 'extern':
            return crate
        if 'git' not in crate:
            return self.resolve_ref(crate['name'])
        return self._resolve_git_extern(crate)

    def _resolve_git_extern(self, ref_crate):
        url = ref_crate['git']
        if url in self.externs:
            return self.externs[url]

        try:
            os.mkdir(self.deps_dir)
        except OSError:
            pass

        ref_dir = os.path.join(self.deps_dir, ref_crate['name'])

        if not os.path.isdir(ref_dir):
            subprocess.check_call([
                'git', 'clone', url,
                '--branch', ref_crate.get('branch', 'master'),
                ref_dir])

        c = self.load_crate(ref_dir)
        self.externs[url] = c
        return c

    def load_crate(self, crate_def):
        toks = crate_def.split('#', 1)
        if len(toks) == 2:
            crate_def, crate_name = toks
        else:
            crate_def = toks[0]
            crate_name = None

        crate_def = os.path.normcase(os.path.abspath(crate_def))
        scope = self._load_scope(crate_def)

        if crate_name is None:
            return scope.crates[0]

        return scope.map[crate_name]

    def resolve_ref(self, name):
        return self.load_crate(self.ref_overrides[name])

_default_templates = {
    'Windows': 'msvc12',
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--template', '-t')
    parser.add_argument('--output-dir', '-C', default='.')
    parser.add_argument('--ref', '-r', action='append', default=[])
    parser.add_argument('cratedef', nargs='?', default='.')
    args = parser.parse_args()

    if args.template is None:
        args.template = _default_templates.get(platform.system(), 'makefile')

    if args.template not in templates:
        print>>sys.stderr, 'Unknown template: {templ}'.format(templ=args.template)
        return 2

    template = templates[args.template]

    ref_overrides = {}
    for ro in args.ref:
        ref, crate_def = ro.split('=', 1)
        ref_overrides[ref] = crate_def

    crate_cache = CrateCache(ref_overrides, args.output_dir)

    try:
        c = crate_cache.load_crate(args.cratedef)
    except CraterError, e:
        print>>sys.stderr, 'error: {}'.format(e.message)
        return 3

    return template(args, c)

if __name__ == '__main__':
    sys.exit(main())
