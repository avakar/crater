import uuid, os.path
import utils

def _gen_items(type, globs, input_dir, output_dir):
    for fglob in globs:
        fnames = list(utils.glob(fglob, input_dir))
        for fname in fnames:
            fname = os.path.relpath(os.path.join(input_dir, fname), output_dir)
            yield '    <{} Include="{}" />\n'.format(type, fname)

def _gen_filter_items(type, globs, input_dir, output_dir, all_filters):
    for fglob in globs:
        fnames = list(utils.glob(fglob, input_dir))
        for fname in fnames:
            filter_name = os.path.relpath(os.path.split(fname)[0], input_dir)
            fname = os.path.relpath(os.path.join(input_dir, fname), output_dir)
            if filter_name and filter_name != '.':
                all_filters.add(filter_name)
                yield '''\
    <{type} Include="{fname}">
      <Filter>{filter}</Filter>
    </{type}>
'''.format(type=type, fname=fname, filter=filter_name)
            else:
                yield '    <{} Include="{}" />\n'.format(type, fname)

uuid_ns = uuid.UUID('{BD60931F-F85F-46A6-BFE9-FCCC48D05554}')
def _gen_guid(seed=None):
    if seed is None:
        return '{{{}}}'.format(str(uuid.uuid4()).upper())

    return '{{{}}}'.format(str(uuid.uuid5(uuid_ns, bytes(seed))).upper())

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

    for c in crates:
        if 'msvc_guid' not in c:
            c['msvc_guid'] = _gen_guid(c['name'])
        c['_msvc_name'] = c['name'] + '.vcxproj'

    for c in crates:
        items = []
        items.extend(
            _gen_items('ClCompile', c.get('sources', []), c.input_dir, args.output_dir))
        items.extend(
            _gen_items('ClInclude', c.get('includes', []), c.input_dir, args.output_dir))

        all_filters = set()
        filter_items = []
        filter_items.extend(
            _gen_filter_items('ClCompile', c.get('sources', []), c.input_dir, args.output_dir, all_filters))
        filter_items.extend(
            _gen_filter_items('ClInclude', c.get('includes', []), c.input_dir, args.output_dir, all_filters))

        include_dirs = []
        refs = []
        for r in c['_link']:
            for ir in r.get('include_roots', []):
                include_dirs.append(os.path.relpath(os.path.join(r.input_dir, ir), args.output_dir))
            refs.append(vcxproj_ref.format(path=r['_msvc_name'], guid=r['msvc_guid']))

        if c['type'] in ('c-exe', 'cpp-exe'):
            proj_type = 'Application'
        elif c['type'] in ('c-lib', 'cpp-lib'):
            proj_type = 'StaticLibrary'
        else:
            raise RuntimeError('Unsupported crate type: {proj_type}'.format(proj_type=proj_type))

        if include_dirs:
            include_dirs = '{};%(AdditionalIncludeDirectories)'.format(';'.join(include_dirs))
        else:
            include_dirs = '%(AdditionalIncludeDirectories)'

        link_libs = ';'.join(c.get('link_libs', []))
        if link_libs:
            link_libs += ';%(AdditionalDependencies)'
        else:
            link_libs = '%(AdditionalDependencies)'

        vcxproj = vcxproj_templ.format(
            name=c['name'],
            project_guid=c['msvc_guid'],
            refs=''.join(refs),
            items=''.join(items),
            proj_type=proj_type,
            include_dirs=include_dirs,
            link_libs=link_libs
            )

        with open(os.path.join(args.output_dir, c['_msvc_name']), 'w') as fout:
            fout.write(vcxproj)

        filters = []
        for filter in sorted(all_filters):
            filters.append('''\
    <Filter Include="{name}">
      <UniqueIdentifier>{guid}</UniqueIdentifier>
    </Filter>
'''.format(name=filter, guid=_gen_guid(filter)))

        with open(os.path.join(args.output_dir, c['_msvc_name'] + '.filters'), 'w') as fout:
            fout.write(filters_templ.format(
                items=''.join(filter_items),
                filters=''.join(filters)
            ))

    sln_name = crate.name
    sln_guid = _gen_guid()

    project_defs = []
    config_maps = []
    for crate in crates:
        project_defs.append(sln_project_def_templ.format(
            sln_guid=sln_guid,
            name=crate['name'],
            project_guid=crate['msvc_guid']
            ))
        config_maps.append(sln_config_map_templ.format(
            project_guid=crate['msvc_guid']
            ))

    sln = sln_templ.format(
        project_defs=''.join(project_defs),
        config_map=''.join(config_maps)
        )

    with open(os.path.join(args.output_dir, sln_name + '.sln'), 'w') as fout:
        fout.write(sln)

    return 0

sln_project_def_templ = '''\
Project("{sln_guid}") = "{name}", "{name}.vcxproj", "{project_guid}"
EndProject
'''

sln_config_map_templ = '''\
		{project_guid}.Debug|Win32.ActiveCfg = Debug|Win32
		{project_guid}.Debug|Win32.Build.0 = Debug|Win32
		{project_guid}.Release|Win32.ActiveCfg = Release|Win32
		{project_guid}.Release|Win32.Build.0 = Release|Win32
'''

sln_templ = '''\

Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio 2013
VisualStudioVersion = 12.0.30501.0
MinimumVisualStudioVersion = 10.0.40219.1
{project_defs}Global
	GlobalSection(SolutionConfigurationPlatforms) = preSolution
		Debug|Win32 = Debug|Win32
		Release|Win32 = Release|Win32
	EndGlobalSection
	GlobalSection(ProjectConfigurationPlatforms) = postSolution
{config_map}	EndGlobalSection
	GlobalSection(SolutionProperties) = preSolution
		HideSolutionNode = FALSE
	EndGlobalSection
EndGlobal
'''

vcxproj_ref = '''\
    <ProjectReference Include="{path}">
      <Project>{guid}</Project>
    </ProjectReference>
'''

vcxproj_templ = '''\
<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="12.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Debug|Win32">
      <Configuration>Debug</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Release|Win32">
      <Configuration>Release</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <ProjectGuid>{project_guid}</ProjectGuid>
    <Keyword>Win32Proj</Keyword>
    <RootNamespace>{name}</RootNamespace>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.Default.props" />
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Debug|Win32'" Label="Configuration">
    <ConfigurationType>{proj_type}</ConfigurationType>
    <UseDebugLibraries>true</UseDebugLibraries>
    <PlatformToolset>v120</PlatformToolset>
    <CharacterSet>Unicode</CharacterSet>
  </PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Release|Win32'" Label="Configuration">
    <ConfigurationType>{proj_type}</ConfigurationType>
    <UseDebugLibraries>false</UseDebugLibraries>
    <PlatformToolset>v120</PlatformToolset>
    <WholeProgramOptimization>true</WholeProgramOptimization>
    <CharacterSet>Unicode</CharacterSet>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.props" />
  <PropertyGroup>
    <IntDir>$(ProjectDir)obj\$(Configuration)\$(ProjectName)\</IntDir>
    <OutDir>$(SolutionDir)bin\$(Configuration)\</OutDir>
  </PropertyGroup>
  <ImportGroup Label="ExtensionSettings">
  </ImportGroup>
  <ImportGroup Label="PropertySheets" Condition="'$(Configuration)|$(Platform)'=='Debug|Win32'">
    <Import Project="$(UserRootDir)\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
  </ImportGroup>
  <ImportGroup Label="PropertySheets" Condition="'$(Configuration)|$(Platform)'=='Release|Win32'">
    <Import Project="$(UserRootDir)\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Debug|Win32'">
    <LinkIncremental>true</LinkIncremental>
  </PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Release|Win32'">
    <LinkIncremental>false</LinkIncremental>
  </PropertyGroup>
  <ItemDefinitionGroup Condition="'$(Configuration)|$(Platform)'=='Debug|Win32'">
    <ClCompile>
      <PrecompiledHeader>
      </PrecompiledHeader>
      <WarningLevel>Level4</WarningLevel>
      <Optimization>Disabled</Optimization>
      <PreprocessorDefinitions>_CRT_SECURE_NO_WARNINGS;_SCL_SECURE_NO_WARNINGS;WIN32;_DEBUG;_CONSOLE;_LIB;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <AdditionalIncludeDirectories>{include_dirs}</AdditionalIncludeDirectories>
    </ClCompile>
    <Link>
      <SubSystem>Console</SubSystem>
      <GenerateDebugInformation>true</GenerateDebugInformation>
      <AdditionalDependencies>{link_libs}</AdditionalDependencies>
    </Link>
    <Lib>
      <AdditionalDependencies>{link_libs}</AdditionalDependencies>
    </Lib>
  </ItemDefinitionGroup>
  <ItemDefinitionGroup Condition="'$(Configuration)|$(Platform)'=='Release|Win32'">
    <ClCompile>
      <WarningLevel>Level3</WarningLevel>
      <PrecompiledHeader>
      </PrecompiledHeader>
      <Optimization>MaxSpeed</Optimization>
      <FunctionLevelLinking>true</FunctionLevelLinking>
      <IntrinsicFunctions>true</IntrinsicFunctions>
      <PreprocessorDefinitions>WIN32;NDEBUG;_CONSOLE;_LIB;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <AdditionalIncludeDirectories>{include_dirs}</AdditionalIncludeDirectories>
    </ClCompile>
    <Link>
      <SubSystem>Console</SubSystem>
      <GenerateDebugInformation>true</GenerateDebugInformation>
      <EnableCOMDATFolding>true</EnableCOMDATFolding>
      <OptimizeReferences>true</OptimizeReferences>
      <AdditionalDependencies>{link_libs}</AdditionalDependencies>
    </Link>
    <Lib>
      <AdditionalDependencies>{link_libs}</AdditionalDependencies>
    </Lib>
  </ItemDefinitionGroup>
  <ItemGroup>
{items}  </ItemGroup>
  <ItemGroup>
{refs}  </ItemGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.targets" />
  <ImportGroup Label="ExtensionTargets">
  </ImportGroup>
</Project>'''

filters_templ = '''\
<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup>
{items}  </ItemGroup>
  <ItemGroup>
{filters}  </ItemGroup>
</Project>'''
