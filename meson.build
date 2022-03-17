project('netplan', 'c',
        version: '0.104',
        license: 'GPL3',
        default_options: [
            'c_std=c99',
            'warning_level=1',
            'werror=true',
        ],
)

glib = dependency('glib-2.0')
gio  = dependency('gio-2.0')
yaml = dependency('yaml-0.1')
uuid = dependency('uuid')

systemd = dependency('systemd')
completions = dependency('bash-completion')
systemd_generator_dir = systemd.get_variable(pkgconfig: 'systemdsystemgeneratordir')
systemd_unit_dir = systemd.get_variable(pkgconfig: 'systemdsystemunitdir')
bash_completions_dir = completions.get_variable(pkgconfig: 'completionsdir', default_value: '/etc/bash_completion.d')

add_project_arguments(
    '-DSBINDIR="' + get_option('sbindir') + '"',
    '-D_XOPEN_SOURCE=500',
    language: 'c')

inc = include_directories('include')
subdir('include')
subdir('src')

#TODO: ship pkgconfig
#pkg_mod = import('pkgconfig')
#pkg_mod.generate(libraries: libnetplan, ...)

#TODO: unit tests
#test_common = find_program('tests/generator/test_common.py')
#test('common', test_common)
