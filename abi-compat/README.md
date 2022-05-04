# Netplan's ABI checker
We're using "abigail" (abigail-tools) to validate libnetplan's ABI.

## HowTo create a ABI reference
The `abidw` tool can be used to generate an ABI XML like this:
```
meson setup build --prefix=/usr
meson compile -C build
abidw build/src/libnetplan.so.0.0 --headers-dir include/ --header-file src/abi.h > abi-compat/jammy_0.104.xml
```

## HowTo compare a ABI
The `abidiff` tool can be used to compare a new library ABI to an existing XML
reference like this (also, see .github/workflows/build-abi.yml):
```
abidiff abi-compat/jammy_0.104.xml build/src/libnetplan.so.0.0 --headers-dir2 include/ --header-file2 src/abi.h --suppressions abi-compat/suppressions.abignore --no-added-syms
```
