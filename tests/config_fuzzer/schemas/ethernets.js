import * as common from "./common.js";

const ethernets_schema = {
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
                ethernets: {
                    type: "object",
                    ...common.minMaxProperties,
                    properties: {
                        renderer: {
                            type: "string",
                            enum: ["networkd", "NetworkManager"]
                        },
                    },
                    patternProperties: {
                        "[azAZ09-]{1,15}": {
                            additionalProperties: false,
                            properties: {
                                ...common.common_properties,
                                "match": {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                        name: {
                                            type: "string",
                                            faker: "lorem.word"
                                        },
                                        driver: {
                                            type: "string",
                                            faker: "lorem.word"
                                        },
                                        macaddress: {
                                            type: "string",
                                            faker: "internet.mac"
                                        }
                                    },
                                },
                                "set-name": {
                                    type: "string"
                                },
                                optional: {
                                    type: "boolean"
                                },
                                wakeonlan: {
                                    type: "boolean"
                                },
                                "emit-lldp": {
                                    type: "boolean"
                                },
                                "receive-checksum-offload": {
                                    type: "boolean"
                                },
                                "transmit-checksum-offload": {
                                    type: "boolean"
                                },
                                "tcp-segmentation-offload": {
                                    type: "boolean"
                                },
                                "tcp6-segmentation-offload": {
                                    type: "boolean"
                                },
                                "generic-segmentation-offload": {
                                    type: "boolean"
                                },
                                "generic-receive-offload": {
                                    type: "boolean"
                                },
                                "large-receive-offload": {
                                    type: "boolean"
                                },
                                macaddress: {
                                    type: "string",
                                    faker: "macaddress.mac"
                                },
                                "ipv6-mtu": {
                                    type: "integer",
                                    minimum: 0
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
                                ...common.networkmanager_settings,
                                ...common.openvswitch
                            },
                            "required": ["match", "set-name"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["ethernets"]
        }
    }
}


export default ethernets_schema;
