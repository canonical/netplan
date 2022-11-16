tests = {
  'test_netplan_parser': false,
  'test_netplan_state': false,
}

cmocka = dependency('cmocka', required: true)

foreach name, should_fail: tests
  exe = executable(name,
    '@0@.c'.format(name),
    include_directories: inc,
    dependencies: [cmocka, glib, gio, yaml, uuid])
  test(name, exe, should_fail: should_fail)
endforeach
