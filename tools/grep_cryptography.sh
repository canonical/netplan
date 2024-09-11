#!/bin/bash
# Grep Netplan's codebase for cryptography related terms, in order to update
# its "Cryptography" documentation in doc/security.md
# BEWARE of --color=always when using "grep -v" to filter out stuff, as the
# output will include control characters for the colors.

GREP="grep \
    --color='always' \
    --exclude-dir=doc \
    --exclude-dir=doc/.sphinx/venv \
    --exclude-dir=debian \
    --exclude-dir=abi-compat \
    --exclude-dir=tests \
    --exclude-dir=.git \
    --exclude=grep_cryptography.sh \
    -EHRin \
    "

eval "$GREP 'crypto'"
eval "$GREP '[^_]hash[^_T]'"  # Ignore GHashTable, g_hash_table
eval "$GREP 'pass' | grep -Evi 'through'"  # Ignore passthrough
eval "$GREP 'private|public|secret|encr|cert' | grep -Evi 'license|netplan'"  # Ignore GPL/NETPLAN_PUBLIC
eval "$GREP 'ssl|tls|sha[0-9]|[^a]md[0-9]'"  # Ignore amd64
# XXX: this produces lots of noise...
eval "$GREP '[^_]key' | grep -Evi 'mapping|value|scalar|yaml|file|char|g_free|clear_'"  # Ignore key-value/mapping-key/YAML_SCALAR_NODE/keyfile/key_file
