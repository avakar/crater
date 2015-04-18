import os.path
import utils, sys

def gen(args, crate):
    q = [crate]
    crates = set(q)
    while q:
        c = q.pop()
        c['_link'] = [c.resolve_ref(ref) for ref in c.get('link', [])]
        for r in c['_link']:
            if r not in crates:
                crates.add(r)
                q.append(r)

    def close_deps(c):
        q = [c]
        res = set()
        while q:
            c = q.pop()
            for d in c['_link']:
                if d not in res:
                    res.add(d)
                    q.append(d)
        return res

    cratefiles = set(os.path.relpath(c.scope.fname, args.output_dir) for c in crates)

    mk_crates = []
    for c in crates:
        sources = []
        for fglob in c['sources']:
            for fname in utils.glob(fglob, c.input_dir):
                sources.append(os.path.relpath(fname, c.input_dir))

        if c['type'] in ('c-exe', 'cpp-exe'):
            templ = exe_crate_templ
            deps = close_deps(c)
        elif c['type'] in ('c-lib', 'cpp-lib'):
            templ = lib_crate_templ
            deps = []
        

        mk_crates.append(templ.format(
            name=c['name'],
            sources=' \\\n\t'.join(sources),
            rootdir=os.path.relpath(c.input_dir, args.output_dir),
            deps=' '.join(d['name'] for d in deps)
            ))

    with open(os.path.join(args.output_dir, 'Makefile'), 'w') as fout:
        fout.write(makefile_templ.format(
            root_crate=crate['name'],
            crates=''.join(mk_crates),
            cratefiles=' '.join(cratefiles),
            main_cratefile=os.path.relpath(crate.scope.fname, args.output_dir),
            crater_cmd='python {}'.format(sys.argv[0])
        ))

    return 0

makefile_templ = '''\
all: bin/{root_crate}

define compile_one

$1_deps += obj/$1/$(notdir $2).d
obj/$1/$(notdir $2).d: $2 | obj/$1
	echo "DEP     $$<"
	$$(CXX) -MM $$(CXXFLAGS) $($1_flags) -std=c++11 $$< -MT "obj/$1/$(notdir $2).o obj/$1/$(notdir $2).d" -MF "$$@"

$1_objs += obj/$1/$(notdir $2).o
obj/$1/$(notdir $2).o: $2 | obj/$1
	echo "CC      $$<"
	$$(CXX) -c $$(CXXFLAGS) $($1_flags) -std=c++11 $$< -o "$$@"

endef

define compile
obj/$1:
	mkdir -p "obj/$1"
$(foreach src,$(addprefix $($1_path)/,$($1_sources)),$(call compile_one,$1,$(src)))
-include $$($1_deps)

endef

define make_lib
$(call compile,$1)
bin/$1.a: $$($1_objs) | bin
	echo "AR      $$@"
	$$(AR) rcs "$$@" $$^

endef

define make_exe
$(call compile,$1)
bin/$1: $$($1_objs) $(patsubst %,bin/%.a,$($1_deps)) | bin
	echo "LNK     $$@"
	$$(CXX) -o "$$@" $$^

endef

{crates}
Makefile: {cratefiles}
	echo "CRATER  {main_cratefile}"
	{crater_cmd} {main_cratefile} -t makefile

.SILENT:
.PHONY: all clean
clean:
	echo "CLEAN"
	rm -r bin obj 2>/dev/null || true

bin:
	mkdir -p "$@"
'''

lib_crate_templ = '''\
{name}_sources := \\
	{sources}

{name}_path := {rootdir}
$(eval $(call make_lib,{name}))

'''

exe_crate_templ = '''\
{name}_sources := \\
	{sources}

{name}_path := {rootdir}
{name}_deps := {deps}
$(eval $(call make_exe,{name}))

'''
