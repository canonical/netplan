sources = files(
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
    dependencies: [glib, gio, yaml, uuid],
    include_directories: inc,
    soversion: 1,
    install: true)

if get_option('testing')
    libnetplan_testing = library(
        'netplan_testing',
        sources,
        gnu_symbol_visibility: 'default',
        c_args: ['-DUNITTESTS'],
        dependencies: [glib, gio, yaml, uuid],
        include_directories: inc,
        soversion: 1,
        install: false)
endif

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
executable(
    'configure',
    'configure.c',
    include_directories: inc,
    link_with: libnetplan,
    dependencies: [glib, gio, yaml, uuid],
    install_dir: libexec_netplan,
    install: true)
