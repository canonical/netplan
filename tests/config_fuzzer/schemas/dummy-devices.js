import * as common from "./common.js";

const dummy_devices_schema = {
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
                "dummy-devices": {
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
                                optional: {
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
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["dummy-devices"]
        }
    }
}


export default dummy_devices_schema;
