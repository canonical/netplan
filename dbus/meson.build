features_h = custom_target(
    build_always_stale: true,
    output: '_features.h',
    input: join_paths(meson.project_source_root(), 'features_h_generator.sh'),
    command: ['sh', '-c', '@INPUT@'],
    install: false,
    capture: true,
)

executable(
    'netplan-dbus',
    '../src/dbus.c',
    features_h,
    include_directories: inc,
    link_with: libnetplan,
    dependencies: [libsystemd, glib, gio, yaml, uuid],
    install_dir: join_paths(get_option('libexecdir'), 'netplan'),
    install: true)

install_data(
    'io.netplan.Netplan.conf',
    install_dir: join_paths(get_option('datadir'), 'dbus-1', 'system.d'))

conf_data = configuration_data()
conf_data.set('ROOTLIBEXECDIR', join_paths(get_option('prefix'), get_option('libexecdir')))
configure_file(
    input: 'io.netplan.Netplan.service.in',
    output: 'io.netplan.Netplan.service',
    configuration: conf_data,
    install: true,
    install_dir: join_paths(get_option('datadir'), 'dbus-1', 'system-services'))

