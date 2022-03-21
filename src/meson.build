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

libnetplan = library(
    'netplan',
    sources,
    gnu_symbol_visibility: 'hidden',
    link_args: ['-T', '../abicompat.lds'],
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
install_symlink(
    'netplan',
    pointing_to: join_paths('..', '..', '..') + join_paths(get_option('prefix'), libexec_netplan, 'generate'),
    install_dir: systemd_generator_dir)
# Install this symlink for legacy reasons, see netplan/cli/utils.py: get_generator_path()
install_symlink(
    'generate',
    pointing_to: join_paths('..', '..') + join_paths(get_option('prefix'), libexec_netplan, 'generate'),
    install_dir: join_paths('/', 'lib', 'netplan'))

