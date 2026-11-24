# The Rust netplan CLI, a drop-in replacement for the Python CLI.
# Built with cargo against the in-tree libnetplan; see meson-cargo.sh.
cargo = find_program('cargo')
cargo_wrapper = find_program('meson-cargo.sh')
cargo_args = [
    meson.current_source_dir(),
    join_paths(meson.current_build_dir(), 'target'),
    join_paths(meson.project_build_root(), 'src'),
]

netplan_rs = custom_target(
    'netplan-rs',
    output: 'netplan',
    command: [cargo_wrapper] + cargo_args + ['build', '@OUTPUT@'],
    depends: libnetplan,
    build_always_stale: true,
    build_by_default: true,
    console: true,
    install: true,
    install_dir: get_option('sbindir'),
)
