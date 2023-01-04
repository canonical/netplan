install_data('../src/netplan.script')
install_symlink(
    'netplan',
    pointing_to: '../share/netplan/netplan.script',
    install_dir: get_option('sbindir'))

netplan_module = join_paths(get_option('datadir'), meson.project_name(), 'netplan')
features_py = custom_target(
    build_always_stale: true,
    output: '_features.py',
    input: join_paths(meson.project_source_root(), 'features_py_generator.sh'),
    command: ['sh', '-c', '@INPUT@'],
    install: true,
    install_dir: netplan_module,
    capture: true,
)

netplan_sources = files(
    '__init__.py',
    'configmanager.py',
    'libnetplan.py',
    'terminal.py')

cli_sources = files(
    'cli/__init__.py',
    'cli/core.py',
    'cli/ovs.py',
    'cli/sriov.py',
    'cli/utils.py')

commands_sources = files(
    'cli/commands/__init__.py',
    'cli/commands/apply.py',
    'cli/commands/generate.py',
    'cli/commands/get.py',
    'cli/commands/info.py',
    'cli/commands/ip.py',
    'cli/commands/migrate.py',
    'cli/commands/set.py',
    'cli/commands/sriov_rebind.py',
    'cli/commands/status.py',
    'cli/commands/try_command.py')

install_data(netplan_sources, install_dir: netplan_module)
install_data(cli_sources, install_dir: join_paths(netplan_module, 'cli'))
install_data(commands_sources, install_dir: join_paths(netplan_module, 'cli', 'commands'))

