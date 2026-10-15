import * as common from "./common.js";

const xfrm_interfaces_schema = {
    type: "object",
    additionalProperties: false,
    properties: {
        network: {
            type: "object",
            additionalProperties: false,
            properties: {
                renderer: {
                    type: "string",
                    enum: ["networkd"]
                },
                version: {
                    type: "integer",
                    minimum: 2,
                    maximum: 2
                },
                ethernets: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                        "eth0": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        }
                    }
                },
                "xfrm-interfaces": {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                        "xfrm0": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "if_id": {
                                    type: "integer",
                                    minimum: 1,
                                    maximum: 4294967295
                                },
                                "independent": {
                                    type: "boolean"
                                },
                                "link": {
                                    type: "string",
                                    enum: ["eth0"]
                                },
                                ...common.common_properties
                            },
                            required: ["if_id"]
                        }
                    }
                }
            },
            required: ["version", "xfrm-interfaces"]
        }
    },
    required: ["network"]
};

export default xfrm_interfaces_schema;