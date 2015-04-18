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

    subdirs = []
    subdir_configs = []
    for c in crates:
        sources = []
        for fglob in c.get('sources', []):
            for fname in utils.glob(fglob, c.input_dir):
                sources.append(os.path.relpath(fname, args.output_dir))

        headers = []
        for fglob in c.get('includes', []):
            for fname in utils.glob(fglob, c.input_dir):
                headers.append(os.path.relpath(fname, args.output_dir))

        deps = close_deps(c)

        if c['type'] in ('c-exe', 'cpp-exe'):
            templ = app_templ
            libs = set('-l{}'.format(d['name']) for d in deps)
        elif c['type'] in ('c-lib', 'cpp-lib'):
            templ = lib_templ
            libs = set()

        include_paths = set()
        for d in deps:
            include_paths.update(
                [os.path.relpath(os.path.join(d.input_dir, ir), args.output_dir) for ir in d.get('include_roots', [])])

        subdirs.append(c['name'])
        subdir_configs.append(subdir_config_templ.format(
            name=c['name'],
            depends=' '.join(d['name'] for d in deps)
            ))
        pro_fname = '{}.pro'.format(c['name'])
        with open(os.path.join(args.output_dir, pro_fname), 'wt') as fout:
            fout.write(templ.format(
                name=c['name'],
                sources=' '.join(sources),
                headers=' '.join(headers),
                include_paths=' '.join(include_paths),
                libs=' '.join(libs),
                ))

    with open(os.path.join(args.output_dir, 'index.pro'), 'wt') as fout:
        fout.write(index_templ.format(
            subdirs=' '.join(subdirs),
            subdir_configs=''.join(subdir_configs),
            ))

    return 0

index_templ = '''\
TEMPLATE = subdirs
SUBDIRS = {subdirs}
{subdir_configs}
'''

subdir_config_templ = '''\
{name}.file = {name}.pro
{name}.depends = {depends}
'''

lib_templ = '''\
TARGET = {name}
TEMPLATE = lib
CONFIG += c++11 staticlib
QT -= core gui
SOURCES = {sources}
HEADERS = {headers}
INCLUDEPATH = {include_paths}
DESTDIR = bin
OBJECTS_DIR = obj/{name}
'''

app_templ = '''\
TARGET = {name}
TEMPLATE = app
CONFIG += c++11
QT -= core gui
SOURCES = {sources}
HEADERS = {headers}
INCLUDEPATH = {include_paths}
LIBS = -Lbin {libs}
DESTDIR = bin
OBJECTS_DIR = obj/{name}
'''
