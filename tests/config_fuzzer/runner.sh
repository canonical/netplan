#!/bin/bash

NETPLANPATH=$1
NUMBER_OF_YAMLS_PER_TYPE=$2

if [ -z ${NUMBER_OF_YAMLS_PER_TYPE} ]
then
    echo "Usage: $0 <netplan source path> <number of YAMLs per netdef type>"
    exit 1
fi

RESULTS_DIR="results_$(date "+%Y%m%d%H%M")"
FAKEDATADIR=fakedata
CC=gcc
BUILDDIR=${NETPLANPATH}/_fuzzer_build
NETPLAN_GENERATE_PATH=${BUILDDIR}/src/generate

export G_DEBUG=fatal_criticals
export LD_LIBRARY_PATH=${BUILDDIR}/src

mkdir ${RESULTS_DIR} || true

if [ ! -d ${BUILDDIR} ]
then
    meson setup --prefix=/usr -Db_sanitize=address ${BUILDDIR} ${NETPLANPATH}
fi
meson compile -C ${BUILDDIR}

${CC} ${NETPLANPATH}/tools/keyfile_to_yaml.c -o keyfile_to_yaml \
    $(pkg-config --cflags --libs glib-2.0) \
    -I${NETPLANPATH}/include -L${BUILDDIR}/src -lnetplan \
    -fsanitize=address,undefined -g

npm install

echo "$(date) - Generating fake data"
node index.js ${NUMBER_OF_YAMLS_PER_TYPE}
echo "$(date) - Done"

echo "$(date) - Testing generator + keyfile loader..."

error=0

for yaml in ${FAKEDATADIR}/*.yaml
do

    rm -rf fakeroot fakeroot2
    mkdir -p fakeroot/etc/netplan fakeroot2/etc/netplan
    cp ${yaml} fakeroot/etc/netplan/

    OUTPUT=$(${NETPLAN_GENERATE_PATH} --root-dir fakeroot 2>&1)
    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
    then
        dir=${RESULTS_DIR}/crash_$(date "+%Y%m%d%H.%N")
        echo "GENERATE CRASHED: ${OUTPUT}"
        echo "YAML THE CAUSED THE CRASH:"
        cat ${yaml}
        echo "GENERATE: Saving crash to ${dir}"
        cp -r fakeroot ${dir}
        error=1
    fi

    if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
    then
        dir=${RESULTS_DIR}/crash_$(date "+%Y%m%d%H.%N")
        echo "GENERATE MEMORY LEAK DETECTED: ${OUTPUT}"
        echo "YAML THE CAUSED THE MEMORY LEAK:"
        cat ${yaml}
        echo "GENERATE: Saving memory leak to ${dir}"
        cp -r fakeroot ${dir}
        error=1
    fi

    echo "YAML: ${yaml}" >> "${RESULTS_DIR}"/generate.log
    echo "${OUTPUT}" >> "${RESULTS_DIR}"/generate.log

    if [ -d fakeroot/run ] && [ -d fakeroot/run/NetworkManager ]
    then
        for keyfile in $(find fakeroot/run/NetworkManager/system-connections/ -type f 2>/dev/null)
        do
            sed -i 's/\[connection\]/\[connection\]\nuuid=c87fb5fc-f607-45f3-8fcd-720b83a742e4/' "${keyfile}"
            filename=$(basename ${keyfile})
            ./keyfile_to_yaml ${keyfile} > fakeroot2/etc/netplan/${filename}.yaml 2>> ${RESULTS_DIR}/keyfile.log

            code=$?
            if [ $code -eq 1 ]
            then
                dir=${RESULTS_DIR}/keyfile_$(date "+%Y%m%d%H.%N")
                echo "Keyfile loader failed: Saving test case to ${dir}"
                cp -r fakeroot ${dir}
            fi
        done

        OUTPUT=$(${NETPLAN_GENERATE_PATH} --root-dir fakeroot2 2>&1)
        code=$?
        if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
        then
            dir=${RESULTS_DIR}/generate_from_keyfile_$(date "+%Y%m%d%H.%N")
            echo "GENERATE FROM KEYFILE GENERATED YAMLS CRASHED: ${OUTPUT}"
            echo "GENERATE: Saving crash to ${dir}"
            cp -r fakeroot2 ${dir}
            error=1
        fi

        if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
        then
            dir=${RESULTS_DIR}/generate_from_keyfile_$(date "+%Y%m%d%H.%N")
            echo "GENERATE FROM KEYFILE GENERATED YAML MEMORY LEAK DETECTED: ${OUTPUT}"
            echo "GENERATE: Saving memory leak to ${dir}"
            cp -r fakeroot2 ${dir}
            error=1
        fi
        echo "${OUTPUT}" >> "${RESULTS_DIR}"/generate_from_keyfile.log

    fi

done

echo "$(date) - Done"

echo "$(date) - Running netplan generate -i"

for yaml in ${FAKEDATADIR}/*.yaml
do
    rm -rf fakeroot3
    mkdir -p fakeroot3/etc/netplan
    cp ${yaml} fakeroot3/etc/netplan/

    OUTPUT=$(${NETPLAN_GENERATE_PATH} --root-dir fakeroot3 -i 2>&1)
    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
    then
        echo "GENERATE --ignore-errors CRASHED"
        cat ${yaml}
        error=1
    fi

    if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
    then
        echo "GENERATE --ignore-errors MEMORY LEAK DETECTED"
        cat ${yaml}
        error=1
    fi

done

echo "$(date) - Done"

exit ${error}
