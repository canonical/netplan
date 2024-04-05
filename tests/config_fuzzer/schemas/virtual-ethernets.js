import * as common from "./common.js";

const common_veth_properties = {
    optional: {
        type: "boolean"
    },
    macaddress: {
        type: "string",
        faker: "macaddress.mac"
    },
    "ipv6-privacy": {
        type: "boolean"
    },
    "link-local": {
        type: "array",
        items: [{
            type: "string",
            enum: ["ipv4", "ipv6"],
        }
        ]
    },
    "ignore-carrier": {
        type: "boolean"
    },
}

const virtual_ethernets_schema = {
    type: "object",
    additionalProperties: false,
    properties: {
        network: {
            type: "object",
            additionalProperties: false,
            properties: {
                renderer: {
                    type: "string",
                    enum: ["networkd", "NetworkManager"]
                },
                version: {
                    type: "integer",
                    minimum: 2,
                    maximum: 2
                },
                "virtual-ethernets": {
                    type: "object",
                    ...common.minMaxProperties,
                    properties: {
                        renderer: {
                            type: "string",
                            enum: ["networkd", "NetworkManager"]
                        },
                    },
                    patternProperties: {
                        "veth0": {
                            additionalProperties: false,
                            required: ["peer"],
                            properties: {
                                peer: {
                                    type: "string",
                                    enum: ["veth1"],
                                },
                                ...common.common_properties,
                                ...common_veth_properties,
                                ...common.networkmanager_settings,
                                ...common.openvswitch
                            },
                        },
                        "veth1": {
                            additionalProperties: false,
                            required: ["peer"],
                            properties: {
                                peer: {
                                    type: "string",
                                    enum: ["veth0"],
                                },
                                ...common.common_properties,
                                ...common_veth_properties,
                                ...common.networkmanager_settings,
                                ...common.openvswitch
                            },
                        },
                        "[azAZ09-]{1,15}": {
                            additionalProperties: false,
                            properties: {
                                peer: {
                                    type: "string",
                                },
                                ...common.common_properties,
                                ...common_veth_properties,
                                ...common.networkmanager_settings,
                                ...common.openvswitch
                            },
                        }
                    },
                    required: ["[azAZ09-]{1,15}", "veth0", "veth1"]
                },
            },
            required: ["virtual-ethernets"]
        }
    }
}


export default virtual_ethernets_schema;
