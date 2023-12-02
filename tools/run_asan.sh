#!/bin/bash

set -e
set -x

BUILDDIR="_leakcheckbuild"
CLEANBUILDDIR="_cleanbuild"
CTESTSBUILDDIR="_ctestsbuild"
CC=gcc

meson setup ${BUILDDIR} -Db_sanitize=address,undefined
meson compile -C ${BUILDDIR} --verbose

tests/ctests/build.sh \
    ${CTESTSBUILDDIR} \
    tests/ctests \
    -Dparent_current_source_dir=$(realpath .) \
    -Dparent_current_build_dir=$(realpath ${BUILDDIR}) \
    -Db_sanitize=address,undefined

meson setup ${CLEANBUILDDIR}
meson compile -C ${CLEANBUILDDIR} --verbose

${CC} tools/keyfile_to_yaml.c -o tools/keyfile_to_yaml \
    -lnetplan $(pkg-config --cflags --libs glib-2.0) \
    -Iinclude -L${BUILDDIR}/src \
    -fsanitize=address,undefined -g

TESTS=$(find ${CTESTSBUILDDIR} -executable -type f)
for test in ${TESTS}
do
    # https://github.com/google/sanitizers/issues/1017
    ASAN_OPTIONS=detect_odr_violation=0 ./${test}
done

mkdir -p ${BUILDDIR}/fakeroot/{etc/netplan,run}

for yaml in examples/*.yaml
do
    filepath=${BUILDDIR}/fakeroot/etc/netplan/${yaml##*/}
    filename=$(basename ${filepath})
    cp ${yaml} ${BUILDDIR}/fakeroot/etc/netplan/
    chmod 600 ${filepath}

    # Set the renderer and check if the new file can be parsed with the new renderer
    # We use the clean build because it will not fail if there's a memory leak
    LD_LIBRARY_PATH="${CLEANBUILDDIR}/src" netplan set --root-dir ${BUILDDIR}/fakeroot --origin-hint ${filename/.yaml/} network.renderer=networkd
    if LD_LIBRARY_PATH="${CLEANBUILDDIR}/src" netplan generate --root-dir ${BUILDDIR}/fakeroot > /dev/null 2>&1
    then
        LD_LIBRARY_PATH="${BUILDDIR}/src" ./${BUILDDIR}/src/generate --root-dir ${BUILDDIR}/fakeroot
    else
        echo "File ${filename} can't be parsed with renderer = networkd"
    fi

    LD_LIBRARY_PATH="${CLEANBUILDDIR}/src" netplan set --root-dir ${BUILDDIR}/fakeroot --origin-hint ${filename/.yaml/} network.renderer=NetworkManager
    if LD_LIBRARY_PATH="${CLEANBUILDDIR}/src" netplan generate --root-dir ${BUILDDIR}/fakeroot > /dev/null 2>&1
    then
        LD_LIBRARY_PATH="${BUILDDIR}/src" ./${BUILDDIR}/src/generate --root-dir ${BUILDDIR}/fakeroot
        for keyfile in $(find ${BUILDDIR}/fakeroot/run/NetworkManager/system-connections/ -type f)
        do
            sed -i 's/\[connection\]/\[connection\]\nuuid=c87fb5fc-f607-45f3-8fcd-720b83a742e4/' "${keyfile}"
            LD_LIBRARY_PATH="${BUILDDIR}/src" ./tools/keyfile_to_yaml "${keyfile}"
        done
    else
        echo "File ${filename} can't be parsed with renderer = NetworkManager"
    fi

    rm ${filepath}
done
