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

# Order: Fedora/Mageia/openSUSE || Debian/Ubuntu
pyflakes = find_program('pyflakes-3', 'pyflakes3', required: false)
pycodestyle = find_program('pycodestyle-3', 'pycodestyle', 'pep8', required: false)
nose = find_program('nosetests-3', 'nosetests3')
pandoc = find_program('pandoc', required: false)
find = find_program('find')

add_project_arguments(
    '-DSBINDIR="' + join_paths(get_option('prefix'), get_option('sbindir')) + '"',
    '-D_XOPEN_SOURCE=700',
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

###########
# Testing #
###########
test_env = [
    'PYTHONPATH=' + meson.current_source_dir(),
    'LD_LIBRARY_PATH=' + join_paths(meson.current_build_dir(), 'src'),
    'NETPLAN_GENERATE_PATH=' + join_paths(meson.current_build_dir(), 'src', 'generate'),
    'NETPLAN_DBUS_CMD=' + join_paths(meson.current_build_dir(), 'dbus', 'netplan-dbus'),
]
test('linting',
     pyflakes,
     args: [meson.current_source_dir()])
test('codestyle',
     pycodestyle,
     args: ['--max-line-length=130', meson.current_source_dir()])
test('documentation',
     find_program('tests/validate_docs.sh'),
     workdir: meson.current_source_dir())
test('legacy-tests',
     find_program('tests/cli.py'),
     timeout: 120,
     env: test_env)
#TODO: split out dbus tests into own test() instance, to run in parallel
test('unit-tests',
     nose,
     args: ['-v', '--with-coverage', meson.current_source_dir()],
     timeout: 600,
     env: test_env)

#TODO: the coverage section should probably be cleaned up a bit
if get_option('b_coverage')
    message('Find coverage reports in <BUILDDIR>/meson-logs/coveragereport[-py]/')
    # Using gcovr instead of lcov/gcov.
    # The 'ninja coverage' command will produce the html/txt reports for C implicitly
    #lcov = find_program('lcov')
    #gcov = find_program('gcov')
    #genhtml = find_program('genhtml')
    gcovr = find_program('gcovr')
    ninja = find_program('ninja')
    grep  = find_program('grep')
    pycoverage = find_program('python3-coverage')
    test('coverage-c-output',
         find_program('ninja'),
         args: ['-C', meson.current_build_dir(), 'coverage'],
         priority: -90, # run before 'coverage-c'
         is_parallel: false)
    test('coverage-c',
         grep,
         args: ['^TOTAL.*100%$', join_paths(meson.current_build_dir(), 'meson-logs', 'coverage.txt')],
         priority: -99, # run last
         is_parallel: false)
    test('coverage-py-output',
         pycoverage,
         args: ['html', '-d', join_paths(meson.current_build_dir(),
                'meson-logs', 'coveragereport-py'), '--omit=/usr*'],
         priority: -99, # run last
         is_parallel: false)
    test('coverage-py',
         pycoverage,
         args: ['report', '--omit=/usr*', '--show-missing', '--fail-under=100'],
         priority: -99, # run last
         is_parallel: false)
endif

