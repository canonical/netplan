tests = {
  'test_netplan_parser': false,
  'test_netplan_state': false,
  'test_netplan_error': false,
  'test_netplan_misc': false,
  'test_netplan_validation': false,
  'test_netplan_keyfile': false,
  'test_netplan_nm': false,
  'test_netplan_openvswitch': false,
}

cmocka = dependency('cmocka', required: true)

foreach name, should_fail: tests
  exe = executable(name,
    '@0@.c'.format(name),
    include_directories: [inc, inc_internal],
    dependencies: [cmocka, glib, gio, yaml, uuid],
    link_with: libnetplan_testing,
    c_args: [
      '-DFIXTURESDIR="' + meson.project_source_root() + '/tests/ctests/fixtures"',
      '-Wno-deprecated-declarations',
      '-D_GNU_SOURCE',
      ],
    install: false,
    )
  test(name, exe, should_fail: should_fail)
endforeach
