sources = files(
    'abi_compat.c',
    'error.c',
    'names.c',
    'netplan.c',
    'networkd.c',
    'nm.c',
    'openvswitch.c',
    'parse.c',
    'parse-nm.c',
    'sriov.c',
    'types.c',
    'util.c',
    'validation.c')

linker_script = meson.project_source_root() / 'abicompat.lds'
libnetplan = library(
    'netplan',
    sources,
    gnu_symbol_visibility: 'hidden',
    link_args: ['-T', linker_script],
    link_depends: linker_script,
    dependencies: [glib, gio, yaml, uuid],
    include_directories: inc,
    soversion: '0.0',
    install: true)

libexec_netplan = join_paths(get_option('libexecdir'), 'netplan')
executable(
    'generate',
    'generate.c',
    include_directories: inc,
    link_with: libnetplan,
    dependencies: [glib, gio, yaml, uuid],
    install_dir: libexec_netplan,
    install: true)
meson.add_install_script(meson_make_symlink,
    join_paths(get_option('prefix'), libexec_netplan, 'generate'),
    join_paths(systemd_generator_dir, 'netplan'))
# FIXME: Drop legacy symlink after 0.107 is released:
# It's only around for legacy reasons, see netplan/cli/utils.py: get_generator_path()
install_symlink(
    'generate',
    pointing_to: join_paths('..', '..') + join_paths(get_option('prefix'), libexec_netplan, 'generate'),
    install_dir: join_paths('/', 'lib', 'netplan'))

