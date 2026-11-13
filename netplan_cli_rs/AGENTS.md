# Agent instructions

This directory contains a Rust reimplementation of the netplan CLI.

Before considering any change to this crate complete, run from this
directory:

```
cargo fmt
cargo clippy
```

All code must be formatted with `cargo fmt` and must not introduce new
`cargo clippy` warnings.

The Rust CLI must stay a drop-in replacement for the Python CLI
(`netplan_cli/`), so also check behaviour against it with the
differential tests in `tests/parity/` (see the header of
`tests/parity/parity.py`). The easiest way to build and run everything is
through meson:

```
meson setup _build-rust --prefix=/usr -Dcli=rust
meson compile -C _build-rust
meson test -C _build-rust rust-lint rust-unit-tests rust-legacy-tests rust-cli-tests parity
```
