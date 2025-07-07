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
NETPLAN_CONFIGURE_PATH=${BUILDDIR}/src/configure

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
    mkdir -p fakeroot/usr/lib/systemd/system-generators
    SD_GENERATOR_PATH=$(pwd)/fakeroot/usr/lib/systemd/system-generators/netplan
    ln -sf $NETPLAN_GENRATE_PATH $SD_GENERATOR_PATH
    GENERATOR_DIR=$(pwd)/fakeroot/run/systemd/generate

    OUTPUT=$(systemd-run --user --pty --collect --wait \
        "--property=ReadOnlyPaths=/" \
        "--property=ReadWritePaths=${GENERATOR_DIR}" \
        "--property=ReadWritePaths=${GENERATOR_DIR}.early" \
        "--property=ReadWritePaths=${GENERATOR_DIR}.late" \
        "--setenv=NETPLAN_PARSER_IGNORE_ERRORS=0" \
        "--setenv=NETPLAN_GENERATE_PATH=${SD_GENERATOR_PATH}" \
        "--setenv=NETPLAN_CONFIGURE_PATH=${NETPLAN_CONFIGURE_PATH}" \
        ${SD_GENERATOR_PATH} --root-dir fakeroot \
        "${GENERATOR_DIR}" "${GENERATOR_DIR}.early" "${GENERATOR_DIR}.late" 2>&1)
    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ] || grep -qE "status=ABRT|status=TRAP|status=SEGV|status=139|status=245|status=133" <<< "$OUTPUT"
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

    OUTPUT=$(${NETPLAN_CONFIGURE_PATH} --root-dir fakeroot 2>&1)
    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
    then
        dir=${RESULTS_DIR}/crash_$(date "+%Y%m%d%H.%N")
        echo "CONFIGURE CRASHED: ${OUTPUT}"
        echo "YAML THE CAUSED THE CRASH:"
        cat ${yaml}
        echo "CONFIGURE: Saving crash to ${dir}"
        cp -r fakeroot ${dir}
        error=1
    fi

    if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
    then
        dir=${RESULTS_DIR}/crash_$(date "+%Y%m%d%H.%N")
        echo "CONFIGURE MEMORY LEAK DETECTED: ${OUTPUT}"
        echo "YAML THE CAUSED THE MEMORY LEAK:"
        cat ${yaml}
        echo "CONFIGURE: Saving memory leak to ${dir}"
        cp -r fakeroot ${dir}
        error=1
    fi

    echo "${OUTPUT}" >> "${RESULTS_DIR}"/generate.log

    mkdir -p fakeroot2/usr/lib/systemd/system-generators
    SD_GENERATOR_PATH=$(pwd)/fakeroot2/usr/lib/systemd/system-generators/netplan
    ln -sf $NETPLAN_GENRATE_PATH $SD_GENERATOR_PATH
    GENERATOR_DIR=$(pwd)/fakeroot2/run/systemd/generate
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

        OUTPUT=$(systemd-run --user --pty --collect --wait \
            "--property=ReadOnlyPaths=/" \
            "--property=ReadWritePaths=${GENERATOR_DIR}" \
            "--property=ReadWritePaths=${GENERATOR_DIR}.early" \
            "--property=ReadWritePaths=${GENERATOR_DIR}.late" \
            "--setenv=NETPLAN_PARSER_IGNORE_ERRORS=0" \
            "--setenv=NETPLAN_GENERATE_PATH=${SD_GENERATOR_PATH}" \
            "--setenv=NETPLAN_CONFIGURE_PATH=${NETPLAN_CONFIGURE_PATH}" \
            ${SD_GENERATOR_PATH} --root-dir fakeroot2 \
            "${GENERATOR_DIR}" "${GENERATOR_DIR}.early" "${GENERATOR_DIR}.late" 2>&1)
        code=$?
        if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ] || grep -qE "status=ABRT|status=TRAP|status=SEGV|status=139|status=245|status=133" <<< "$OUTPUT"
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

        OUTPUT=$(${NETPLAN_CONFIGURE_PATH} --root-dir fakeroot2 2>&1)
        code=$?
        if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
        then
            dir=${RESULTS_DIR}/generate_from_keyfile_$(date "+%Y%m%d%H.%N")
            echo "CONFIGURE FROM KEYFILE GENERATED YAMLS CRASHED: ${OUTPUT}"
            echo "CONFIGURE: Saving crash to ${dir}"
            cp -r fakeroot2 ${dir}
            error=1
        fi

        if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
        then
            dir=${RESULTS_DIR}/generate_from_keyfile_$(date "+%Y%m%d%H.%N")
            echo "CONFIGURE FROM KEYFILE GENERATED YAML MEMORY LEAK DETECTED: ${OUTPUT}"
            echo "CONFIGURE: Saving memory leak to ${dir}"
            cp -r fakeroot2 ${dir}
            error=1
        fi
        echo "${OUTPUT}" >> "${RESULTS_DIR}"/generate_from_keyfile.log
    fi
done

echo "$(date) - Done"

echo "$(date) - Running netplan generate -i"

mkdir -p fakeroot3/usr/lib/systemd/system-generators
SD_GENERATOR_PATH=$(pwd)/fakeroot3/usr/lib/systemd/system-generators/netplan
ln -sf $NETPLAN_GENRATE_PATH $SD_GENERATOR_PATH
GENERATOR_DIR=$(pwd)/fakeroot3/run/systemd/generate
for yaml in ${FAKEDATADIR}/*.yaml
do
    rm -rf fakeroot3
    mkdir -p fakeroot3/etc/netplan
    cp ${yaml} fakeroot3/etc/netplan/

    OUTPUT=$(systemd-run --user --pty --collect --wait \
        "--property=ReadOnlyPaths=/" \
        "--property=ReadWritePaths=${GENERATOR_DIR}" \
        "--property=ReadWritePaths=${GENERATOR_DIR}.early" \
        "--property=ReadWritePaths=${GENERATOR_DIR}.late" \
        "--setenv=NETPLAN_GENERATE_PATH=${SD_GENERATOR_PATH}" \
        "--setenv=NETPLAN_CONFIGURE_PATH=${NETPLAN_CONFIGURE_PATH}" \
        ${SD_GENERATOR_PATH} --root-dir fakeroot3 -i \
        "${GENERATOR_DIR}" "${GENERATOR_DIR}.early" "${GENERATOR_DIR}.late" 2>&1)    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ] || grep -qE "status=ABRT|status=TRAP|status=SEGV|status=139|status=245|status=133" <<< "$OUTPUT"
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

    OUTPUT=$(${NETPLAN_CONFIGURE_PATH} --root-dir fakeroot3 -i 2>&1)
    code=$?
    if [ $code -eq 139 ] || [ $code -eq 245 ] || [ $code -eq 133 ]
    then
        echo "CONFIGURE --ignore-errors CRASHED"
        cat ${yaml}
        error=1
    fi

    if grep 'detected memory leaks' <<< "$OUTPUT" > /dev/null
    then
        echo "CONFIGURE --ignore-errors MEMORY LEAK DETECTED"
        cat ${yaml}
        error=1
    fi
done

echo "$(date) - Done"

exit ${error}
