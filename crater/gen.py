import os, toposort

def gen_msbuild(path, mapping, g):
    templ = '''\
<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
{deps}  </PropertyGroup>
</Project>'''

    prefix = g.get('prop_prefix', 'dep_')
    file = g.get('file', 'deps.props')

    deps = []
    for name, target_dir in mapping.items():
        deps.append('    <{prefix}{name}>{dir}</{prefix}{name}>\n'.format(prefix=prefix, name=name, dir=target_dir))

    content = templ.format(deps=''.join(deps))
    with open(os.path.join(path, file), 'wb') as fout:
        fout.write(content.encode())

def gen_cmake(mapping, g):
    prefix = g.get('prop_prefix', 'dep_')

    deps = []
    for name, target_dir in mapping.items():
        if name != 'self':
            deps.append('set({prefix}{name} {dir})\n'.format(prefix=prefix, name=name, dir=target_dir))

    return deps

def topo_sort_crates(lock):
    spec = {}
    for crate in lock.crates():
        if crate.is_self_crate():
            continue
        deps = set(tgt for name, tgt in crate.deps())
        spec[crate] = deps

    r = []
    for chunk in toposort.toposort(spec):
        r.extend(chunk)
    return r

def gen(lock):
    for crate in lock.crates():
        g = crate._gen
        d = g.get('msbuild')
        if d is None:
            continue

        mapping = { 'self': os.path.abspath(crate.path) }
        for dep, target in crate.deps():
            mapping[dep] = os.path.abspath(target.path)

        gen_msbuild(crate.path, mapping, d)

    for crate in lock.crates():
        g = crate._gen

        if not g and crate.dep_specs():
            g = { 'cmake': {} }

        d = g.get('cmake')
        if d is None:
            continue

        mapping = { 'self': crate.name }
        for dep, target in crate.deps():
            mapping[dep] = target.name

        content = gen_cmake(mapping, d)

        if crate.is_self_crate():
            content.append('\n')
            for c in topo_sort_crates(lock):
                if os.path.isfile(os.path.join(c.path, 'CMakeLists.txt')):
                    content.append('add_subdirectory({dep_path} EXCLUDE_FROM_ALL)\n'.format(dep_path=os.path.relpath(c.path, crate.path).replace('\\', '/')))

        if content:
            with open(os.path.join(crate.path, g.get('file', 'deps.cmake')), 'wb') as fout:
                content = ''.join(content)
                fout.write(content.encode())
