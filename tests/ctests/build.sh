#!/bin/sh

BUILDDIR="$1"; shift
meson setup ${BUILDDIR} $*
meson compile -C ${BUILDDIR} --verbose

if [ "$(basename $0)" = "run.sh" ]; then
    meson test -C ${BUILDDIR}
fi
