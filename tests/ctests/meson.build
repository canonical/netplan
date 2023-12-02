project('ctests', 'c')

add_project_arguments(
    '-DSBINDIR="' + join_paths(get_option('prefix'), get_option('sbindir')) + '"',
    '-D_GNU_SOURCE',
    language: 'c')

tests = {
  'test_netplan_parser': false,
  'test_netplan_state': false,
  'test_netplan_error': false,
  'test_netplan_misc': false,
  'test_netplan_deprecated': false,
  'test_netplan_validation': false,
  'test_netplan_keyfile': false,
  'test_netplan_nm': false,
  'test_netplan_openvswitch': false,
}

glib = dependency('glib-2.0')
gio  = dependency('gio-2.0')
yaml = dependency('yaml-0.1')
uuid = dependency('uuid')
cmocka = dependency('cmocka', required: true)
netplan = meson.get_compiler('c').find_library(
    'netplan',
    dirs: [join_paths(get_option('parent_current_build_dir'), 'src')])

foreach name, should_fail: tests
  exe = executable(name,
    '@0@.c'.format(name),
    include_directories: [
      join_paths(get_option('parent_current_source_dir'), 'include'),
      join_paths(get_option('parent_current_source_dir'), 'src'),
    ],
    dependencies: [cmocka, glib, gio, yaml, uuid, netplan],
    c_args: [
      '-DFIXTURESDIR="' + meson.project_source_root() + '/fixtures"',
      '-Wno-deprecated-declarations',
      '-D_GNU_SOURCE',
      ],
    )
  test(name, exe, should_fail: should_fail)
endforeach
