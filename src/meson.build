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

