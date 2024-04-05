import * as common from "./common.js";

const openvswitch_schema = {
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
                bridges: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                        "ovsbr0": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "interfaces": {
                                    type: "array",
                                    items: {
                                        type: "string",
                                        enum: ["port1"],
                                    }
                                }
                            }
                        },
                        "ovsbr1": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "interfaces": {
                                    type: "array",
                                    items: {
                                        type: "string",
                                        enum: ["port2"],
                                    }
                                }
                            }
                        },
                    },
                    required: ["ovsbr0", "ovsbr1"]
                },
                openvswitch: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                        "external-ids": {
                            type: "object",
                        },
                        "other-config": {
                            type: "object",
                        },
                        protocols: {
                            type: "array",
                            items: {
                                type: "string",
                                enum: ["OpenFlow10", "OpenFlow11", "OpenFlow12", "OpenFlow13", "OpenFlow14", "OpenFlow15"]
                            }
                        },
                        ssl: {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "ca-cert": {
                                    type: "string",
                                    faker: "system.filePath"
                                },
                                "certificate": {
                                    type: "string",
                                    faker: "system.filePath"
                                },
                                "private-key": {
                                    type: "string",
                                    faker: "system.filePath"
                                },
                            }
                        },
                        ports: {
                            type: "array",
                            maxItems: 1,
                            minItems: 1,
                            items: {
                                type: "array",
                                enum: [["port1", "port2"]]
                                
                            }
                        }
                    },
                    required: ["ports"]
                },
            },
            required: ["bridges", "openvswitch"]
        }
    }
}


export default openvswitch_schema;
