import os

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
        fout.write(content)


def gen(path, mapping, g):
    d = g.get('msbuild')
    if d is not None:
        gen_msbuild(path, mapping, d)
