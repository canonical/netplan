project('netplan', 'c',
        version: '1.0',
        license: 'GPL3',
        default_options: [
            'c_std=c99',
            'warning_level=2',
            'werror=true',
        ],
        meson_version: '>= 0.61.0',
)

glib = dependency('glib-2.0')
gio  = dependency('gio-2.0')
yaml = dependency('yaml-0.1')
uuid = dependency('uuid')
libsystemd = dependency('libsystemd')

meson_make_symlink = meson.current_source_dir() + '/tools/meson-make-symlink.sh'

systemd = dependency('systemd')
completions = dependency('bash-completion')
systemd_generator_dir = systemd.get_variable(pkgconfig: 'systemdsystemgeneratordir')
bash_completions_dir = completions.get_variable(pkgconfig: 'completionsdir', default_value: '/etc/bash_completion.d')

# Order: Fedora/Mageia/openSUSE || Debian/Ubuntu
pyflakes = find_program('pyflakes-3', 'pyflakes3', required: false)
pycodestyle = find_program('pycodestyle-3', 'pycodestyle', 'pep8', required: false)
pytest = find_program('pytest-3', 'pytest3')  # also requires the pytest-cov plugin
pycoverage = find_program('coverage-3', 'python3-coverage')
pandoc = find_program('pandoc', required: false)
find = find_program('find')

add_project_arguments(
    '-DSBINDIR="' + join_paths(get_option('prefix'), get_option('sbindir')) + '"',
    '-D_GNU_SOURCE',
    language: 'c')

inc = include_directories('include')
inc_internal = include_directories('src')
subdir('include')
subdir('src')
subdir('dbus')
subdir('netplan_cli')
subdir('python-cffi')
subdir('examples')
subdir('doc')
subdir('data')

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
    'PYTHONPATH=' + join_paths(meson.current_build_dir(), 'python-cffi') + ':' + meson.current_source_dir(),
    'LD_LIBRARY_PATH=' + join_paths(meson.current_build_dir(), 'src'),
    'NETPLAN_GENERATE_PATH=' + join_paths(meson.current_build_dir(), 'src', 'generate'),
    'NETPLAN_DBUS_CMD=' + join_paths(meson.current_build_dir(), 'dbus', 'netplan-dbus'),
    'COVERAGE_PROCESS_START=' + join_paths(meson.current_source_dir(), '.coveragerc'),
    'G_DEBUG=fatal_criticals',
]

if get_option('unit_testing')
  subdir('tests/ctests')
endif

#FIXME: exclude doc/env/
test('linting',
     pyflakes,
     timeout: 100,
     args: [meson.current_source_dir()])
test('codestyle',
     pycodestyle,
     timeout: 100,
     args: ['--max-line-length=130', '--exclude=doc/env,*meson-private/pycompile.py', meson.current_source_dir()])
test('documentation',
     find_program('tests/validate_docs.sh'),
     timeout: 100,
     workdir: meson.current_source_dir())
test('legacy-tests',
     find_program('tests/cli_legacy.py'),
     timeout: 600,
     env: test_env)
#TODO: split out dbus tests into own test() instance, to run in parallel
test('unit-tests',
     pycoverage,
     args: ['run', '-a', '-m', 'pytest', '-s', '-v', '--cov-append', meson.current_source_dir()],
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
    cat  = find_program('cat')
    test('coverage-c-output',
         find_program('ninja'),
         args: ['-C', meson.current_build_dir(), 'coverage'],
         timeout: 60,
         priority: -90, # run before 'coverage-c'
         is_parallel: false)
    test('coverage-c-cat',
         cat,
         args: [join_paths(meson.current_build_dir(), 'meson-logs', 'coverage.txt')],
         priority: -98, # run before 'coverage-c'
         is_parallel: false)
    test('coverage-c',
         grep,
         args: ['^TOTAL.*100%$', join_paths(meson.current_build_dir(), 'meson-logs', 'coverage.txt')],
         priority: -99, # run last
         is_parallel: false)
    test('coverage-py-combine',
         pycoverage,
         args: ['combine', '-a', meson.current_build_dir()],
         priority: -90, # run before 'coverage-py-output'
         is_parallel: false)
    test('coverage-py-output',
         pycoverage,
         args: ['html', '-d', join_paths(meson.current_build_dir(),
                'meson-logs', 'coveragereport-py'), '--omit=/usr/*'],
         priority: -95, # run before 'coverage-py'
         is_parallel: false)
    test('coverage-py',
         pycoverage,
         args: ['report', '--omit=/usr/*', '--show-missing', '--fail-under=100'],
         priority: -99, # run last
         is_parallel: false)
endif

