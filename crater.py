import sys, argparse, os.path
import pytoml as toml
import template_msvc12

templates = {
    'msvc12': template_msvc12.gen,
    }

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

class Scope:
    def __init__(self, cache, crate_def, cratefile):
        self.cache = cache
        self.crate_def = crate_def
        self.input_dir = crate_def
        self.crates = [Crate(c, self) for c in cratefile.get('crate', [])]
        self.map = { crate.name: crate for crate in self.crates }

    def resolve_ref(self, name):
        if name in self.map:
            return self.map[name]
        return self.cache.resolve_ref(name)

class CrateCache:
    def __init__(self, ref_overrides):
        self.ref_overrides = ref_overrides
        self.scopes = {}

    def _load_scope(self, crate_def):
        if crate_def in self.scopes:
            return self.scopes[crate_def]

        with open(os.path.join(crate_def, 'Cratefile'), 'r') as fin:
            cratefile = toml.load(fin)
            input_dir = crate_def

        scope = Scope(self, crate_def, cratefile)
        self.scopes[crate_def] = scope
        return scope

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

def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--template', '-t', default='msvc12')
    parser.add_argument('--output-dir', '-C', default='.')
    parser.add_argument('--ref', '-r', action='append', default=[])
    parser.add_argument('cratedef', nargs='?', default='.')
    args = parser.parse_args()

    if args.template not in templates:
        print>>sys.stderr, 'Unknown template: {templ}'.format(templ=args.template)
        return 2

    template = templates[args.template]

    ref_overrides = {}
    for ro in args.ref:
        ref, crate_def = ro.split('=', 1)
        ref_overrides[ref] = crate_def

    crate_cache = CrateCache(ref_overrides)
    c = crate_cache.load_crate(args.cratedef)

    return template(args, c)

if __name__ == '__main__':
    sys.exit(_main())
