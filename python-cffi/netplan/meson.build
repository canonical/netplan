pymod = import('python')
python = pymod.find_installation(
    'python3',
    modules: ['cffi']
)
python_dep = python.dependency(required: true)

cffi_srcs = configure_file(
    command: [
        python,
        files('_build_cffi.py'),
        join_paths(meson.project_source_root(), 'include'),
        join_paths(meson.current_build_dir(), 'src'),
    ],
    output: '_netplan_cffi.c',
)

# Generation of the Python binary extension through meson.
cffi_pyext = python.extension_module(
    '_netplan_cffi',
    cffi_srcs,
    dependencies: [python_dep, glib, uuid],
    include_directories: [inc, inc_internal],
    link_with: [libnetplan],
    subdir: 'netplan',
    install: true,
    limited_api: '3.10',
)

bindings_sources = [
  '__init__.py',
  'netdef.py',
  'parser.py',
  'state.py',
  '_utils.py']

# Copy module sources into build-dir,
# so they can be importet together with the binary extension
foreach src : bindings_sources
    custom_target(
        input: src,
        output: src,
        command: ['cp', '@INPUT@', join_paths(meson.current_build_dir(), '@PLAINNAME@')],
        build_always_stale: true,
        build_by_default: true,
        depends: cffi_pyext)
endforeach

bindings = python.install_sources(
    [bindings_sources],
    subdir: 'netplan')
