#!/bin/sh
# Build or check the Rust netplan CLI for meson.
#
# Usage: meson-cargo.sh SRCDIR TARGETDIR LIBDIR build OUTPUT
#        meson-cargo.sh SRCDIR TARGETDIR LIBDIR test|lint
#
# Runs cargo from SRCDIR so rust-toolchain.toml applies, links against the
# libnetplan in LIBDIR (the meson build tree) and keeps cargo's output in
# TARGETDIR inside the meson build directory.
set -eu
SRCDIR="$1"; TARGETDIR="$2"; LIBDIR="$3"; ACTION="$4"
export NETPLAN_LIB_DIR="$LIBDIR"
export CARGO_TARGET_DIR="$TARGETDIR"
OUTPUT="${5:-}"
case "$OUTPUT" in
    ""|/*) ;;
    *) OUTPUT="$PWD/$OUTPUT" ;;
esac
cd "$SRCDIR"
case "$ACTION" in
    build)
        cargo build --release --locked
        cp "$TARGETDIR/release/netplan" "$OUTPUT"
        ;;
    test)
        LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" cargo test --release --locked
        ;;
    lint)
        cargo fmt --check
        cargo clippy --release --locked -- -D warnings
        ;;
    *)
        echo "unknown action: $ACTION" >&2
        exit 2
        ;;
esac
