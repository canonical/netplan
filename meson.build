project('netplan', 'c',
        version: '0.104',
        license: 'GPL3',
        default_options: [
            'c_std=c99',
            'warning_level=1',
            'werror=true',
        ],
        meson_version: '>= 0.61.0',
)

glib = dependency('glib-2.0')
gio  = dependency('gio-2.0')
yaml = dependency('yaml-0.1')
uuid = dependency('uuid')
libsystemd = dependency('libsystemd')

systemd = dependency('systemd')
completions = dependency('bash-completion')
systemd_generator_dir = systemd.get_variable(pkgconfig: 'systemdsystemgeneratordir')
bash_completions_dir = completions.get_variable(pkgconfig: 'completionsdir', default_value: '/etc/bash_completion.d')

pandoc = find_program('pandoc', required: false)
find = find_program('find')

add_project_arguments(
    '-DSBINDIR="' + get_option('sbindir') + '"',
    '-D_XOPEN_SOURCE=500',
    language: 'c')

message('Generating the _features.[py|h] code')
#XXX: this is ugly as it produces artifacts in the source directory
run_command('features_h_generator.sh', check: true)
run_command('features_py_generator.sh', check: true)

inc = include_directories('include')
subdir('include')
subdir('src')
subdir('dbus')
subdir('netplan')
subdir('examples')
subdir('doc')

pkg_mod = import('pkgconfig')
pkg_mod.generate(
    libraries: libnetplan,
    subdirs: ['netplan'],
    name: 'libnetplan',
    filebase: 'netplan',
    description: 'YAML network configuration abstraction runtime library')

install_data(
    'netplan.completions',
    rename: 'netplan',
    install_dir: bash_completions_dir)

#TODO: unit tests
#test_common = find_program('tests/generator/test_common.py')
#test('common', test_common)
