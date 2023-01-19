tests = {
  'test_netplan_parser': false,
  'test_netplan_state': false,
  'test_netplan_error': false,
  'test_netplan_misc': false,
  'test_netplan_deprecated': false,
  'test_netplan_validation': false,
}

cmocka = dependency('cmocka', required: true)

inc_tests = include_directories('../../src')
foreach name, should_fail: tests
  exe = executable(name,
    '@0@.c'.format(name),
    include_directories: [inc, inc_tests],
    dependencies: [cmocka, glib, gio, yaml, uuid],
    c_args: ['-Wno-deprecated-declarations', '-DFIXTURESDIR="' + meson.project_source_root() + '/tests/ctests/fixtures"'],
    )
  test(name, exe, should_fail: should_fail)
endforeach
