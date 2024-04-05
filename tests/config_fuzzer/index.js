import writeYamlFile from 'write-yaml-file';
import { JSONSchemaFaker } from "json-schema-faker";
import { faker } from '@faker-js/faker';

import * as fs from 'node:fs';

import ethernets_schema from './schemas/ethernets.js';
import wifis_schema from './schemas/wifis.js';
import vrfs_schema from './schemas/vrfs.js';
import vlans_schema from './schemas/vlans.js';
import bridges_schema from './schemas/bridges.js';
import bonds_schema from './schemas/bonds.js';
import nmdevices_schema from './schemas/nm-devices.js';
import { wireguard_schema, sit_schema, vxlan_schema } from './schemas/tunnels.js';
import modems_schema from './schemas/modems.js';
import openvswitch_schema from './schemas/openvswitch.js'
import dummy_devices_schema from './schemas/dummy-devices.js';
import virtual_ethernets_schema from './schemas/virtual-ethernets.js';

import { randomBytes } from "node:crypto";

JSONSchemaFaker.extend('faker', () => {
    faker.macaddress = {
        mac: _ => {
            var items = [faker.internet.mac(), "permanent", "random", "stable", "preserve"];
            return items[Math.floor(Math.random() * 1000) % 4];
        }
    },
    faker.ipv4 = {
        withprefix: _ => {
            return faker.internet.ipv4() + '/24';
        }
    }
    faker.ipv6 = {
        withprefix: _ => {
            return faker.internet.ipv6() + '/64';
        }
    }
    faker.ipv4_or_ipv6 = {
        withprefix: _ => {
            if (Math.floor(Math.random() * 1000) % 2 == 0) {
                return faker.internet.ipv6() + '/64';
            } else {
                return faker.internet.ipv4() + '/24';
            }
        },
        withoutprefix: _ => {
            if (Math.floor(Math.random() * 1000) % 2 == 0) {
                return faker.internet.ipv6();
            } else {
                return faker.internet.ipv4();
            }
        },
        withport: _ => {
            var port = Math.floor(Math.random() * 65536);
            if (Math.floor(Math.random() * 1000) % 2 == 0) {
                return faker.internet.ipv6() + ":" + port.toString();
            } else {
                return faker.internet.ipv4() + ":" + port.toString();
            }
        }
    }
    faker.openvswitch = {
        controller_address: _ => {
            var number = Math.floor(Math.random() * 65536) % 6;
            if (number == 0) {
                return "unix:" + faker.system.filePath();
            } else if (number == 1) {
                return "punix:" + faker.system.filePath();
            } else if (number == 2) {
                return "tcp:" + faker.internet.ipv4() + ":" + faker.internet.port();
            } else if (number == 3) {
                return "ptcp:" + faker.internet.port() + ":" + faker.internet.ipv4();
            } else if (number == 4) {
                return "ssl:" + faker.internet.ipv4() + ":" + faker.internet.port();
            } else if (number == 5) {
                return "pssl:" + faker.internet.port() + ":" + faker.internet.ipv4();
            }
        }
    }
    return faker;
});


function apply_fixes(object, object_type) {
    var renderer = ""
    if (!("network" in object) || !(object_type in object["network"])) {
        return;
    }

    if ("renderer" in object) {
        renderer = object["renderer"];
    }

    var interfaces = object["network"][object_type]

    if ("renderer" in object["network"]) {
        renderer = object["network"]["renderer"];
    }

    Object.keys(interfaces).forEach(function (key) {
        var has_address_options = false;

        if (key != "renderer") {
            var iface = interfaces[key];

            if ("renderer" in iface) {
                renderer = iface["renderer"];
            }

            /*
            If addresses as objects were generated, set the renderer to networkd.
            NetworkManager doesn't support addresses options
            */
            if ("addresses" in iface) {
                Object.keys(iface["addresses"]).forEach(function (key) {
                    if (typeof iface["addresses"][key] === 'object') {
                        interfaces["renderer"] = "networkd";
                        object["network"]["renderer"] = "networkd";
                        iface["renderer"] = "networkd";
                        renderer = "networkd";
                        has_address_options = true;
                        return;
                    }
                });
            }

            /*
            If it has the networkmanager property and the renderer is not NetworkManager delete it
            */
            if ("networkmanager" in iface && renderer != "NetworkManager") {
                delete object["network"][object_type][key]["networkmanager"];
            } else {
                /*
                If the interface doesn't have addresses options, make sure the interface itself has renderer: NetworkManager
                */
                if (has_address_options == false) {
                    iface["renderer"] = "NetworkManager";
                }
            }

            if (object_type == "wifis") {
                if ("access-points" in iface) {
                    Object.keys(iface["access-points"]).forEach(function (ap_key) {
                        if ("networkmanager" in iface["access-points"][ap_key] && renderer != "NetworkManager") {
                            delete object["network"][object_type][key]["access-points"][ap_key]["networkmanager"];
                        } else {
                            /*
                            If the interface doesn't have addresses options, make sure the interface itself has renderer: NetworkManager
                            */
                            if (has_address_options == false) {
                                iface["renderer"] = "NetworkManager";
                            }
                        }
                    });
                }
            }
        }
    });
}


function getRandomFilename() {
    return randomBytes(32).toString('hex') + '.yaml';
}

function writeSchema(schema) {
    var filename = getRandomFilename();
    writeYamlFile.sync(`${destDir}/${filename}`, schema, {mode: 0o600});
}

function generateYAML(schema) {
    return JSONSchemaFaker.generate(schema);
}

const destDir = "fakedata";
fs.mkdirSync(destDir, { recursive: true });

var numberOfFiles = 1;

if (process.argv.length == 3) {
    numberOfFiles = parseInt(process.argv[2]);
}

while (numberOfFiles > 0) {

    numberOfFiles = numberOfFiles - 1;

    var schema = generateYAML(ethernets_schema);
    apply_fixes(schema, "ethernets");
    writeSchema(schema);

    schema = generateYAML(wifis_schema);
    apply_fixes(schema, "wifis");
    writeSchema(schema);

    schema = generateYAML(vrfs_schema);
    apply_fixes(schema, "vrfs");
    writeSchema(schema);

    schema = generateYAML(vlans_schema);
    apply_fixes(schema, "vlans");
    writeSchema(schema);

    schema = generateYAML(bridges_schema);
    apply_fixes(schema, "bridges");
    writeSchema(schema);

    schema = generateYAML(bonds_schema);
    apply_fixes(schema, "bonds");
    writeSchema(schema);

    schema = generateYAML(wireguard_schema);
    apply_fixes(schema, "tunnels");
    writeSchema(schema);

    schema = generateYAML(sit_schema);
    apply_fixes(schema, "tunnels");
    writeSchema(schema);

    schema = generateYAML(vxlan_schema);
    apply_fixes(schema, "vxlans");
    writeSchema(schema);

    schema = generateYAML(nmdevices_schema);
    apply_fixes(schema, "nmdevices");
    writeSchema(schema);

    schema = generateYAML(modems_schema);
    apply_fixes(schema, "modems");
    writeSchema(schema);

    schema = generateYAML(openvswitch_schema);
    apply_fixes(schema, "ovs");
    writeSchema(schema);

    schema = generateYAML(dummy_devices_schema);
    apply_fixes(schema, "dummy-devices");
    writeSchema(schema);

    schema = generateYAML(virtual_ethernets_schema);
    apply_fixes(schema, "virtual-ethernets");
    writeSchema(schema);
}
