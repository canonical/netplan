#!/bin/bash
# find everything that looks like
#     {"driver", YAML_SCALAR_NODE,...,
# extract the thing in quotes.

# sanity check: make sure none have disappeared, as might happen from a reformat.
count=$(sed -n 's/[ ]\+{"\([a-z0-9-]\+\)", YAML_[A-Z]\+_NODE.*/\1/p' src/parse.c | sort | uniq | wc -l)
# 71 is based on the 0.36.1 definitions, and should be updated periodically.
if [ $count -lt 71 ]; then
    echo "ERROR: fewer YAML keys defined in src/parse.c than expected!"
    echo "       Has the file been reformatted or refactored? If so, modify"
    echo "       validate_docs.sh appropriately."
    exit 1
fi

# iterate through the keys
for term in $(sed -n 's/[ ]\+{"\([a-z0-9-]\+\)", YAML_[A-Z]\+_NODE.*/\1/p' src/parse.c | sort | uniq); do
    # it can be documented in the following ways.
    # 1. "Properties for device type ``blah:``
    if egrep "## Properties for device type \`\`$term:\`\`" doc/netplan.md > /dev/null; then
	continue
    fi

    # 2. "[blah, ]``blah``[, ``blah2``]: (scalar|bool|...)
    if egrep "\`\`$term\`\`.*\((scalar|bool|mapping|sequence of scalars)\)" doc/netplan.md > /dev/null; then
	continue
    fi

    # 3. we give a pass to network and version
    if [[ $term = "network" ]] || [[ $term = "version" ]]; then
	continue
    fi

    # 4. search doesn't get a full description but it's good enough
    if [[ $term = "search" ]]; then
	continue
    fi

    # 5. gratuit_i_ous arp gets a special note
    if [[ $term = "gratuitious-arp" ]]; then
	continue
    fi

    echo ERROR: The key "$term" is defined in the parser but not documented.
    exit 1
done
echo "validate_docs: OK"
