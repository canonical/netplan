config_fuzzer uses [json-schema-faker](https://github.com/json-schema-faker/json-schema-faker) to generate random Netplan YAML files from a JSON schema.

## How to use it

* Clone Netplan and install the dependencies
```
git clone https://github.com/canonical/netplan.git
cd netplan/tests/config_fuzzer
npm install
```

You will also need to install `nodejs` and `npm`.

* Run it
```
node index.js
```

A bunch of YAML files will be created in the directory `fakedata`.

You can create more YAMLs per device type with:

```
node index.js 100
```

In this example, 100 YAMLs per device type will be created.

* Run netplan against the YAMLs

```
mkdir -p fakeroot/etc/netplan
cp fakedata/someyaml.yaml fakeroot/etc/netplan/
netplan generate --root-dir fakeroot
```

* Using the runner.sh script

You can also automatically test netplan against all the generated YAML files:

```
bash runner.sh /path/to/netplan_source_code 100
```

This script will build netplan, generate the random YAMLs and test the netplan generator against each one of them.

This script will do these things in this order:

 * Build Netplan with ASAN enabled
 * Build the tools/keyfile_to_yaml with ASAN from Netplan
 * Install the node modules
 * Generate a number of random Netplan YAMLs
 * Call `netplan generate` for each one of them separately
 * If it results in NetworkManager files, try to load them with the keyfile_to_yaml tool
 * Call netplan generate again for the YAMLs created by the keyfile_to_yaml tool
