import * as common from "./common.js";

const bridges_schema = {
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
                        },
                        "eth1": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth2": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        }
                    },
                    required: ["eth0", "eth1", "eth2"]
                },
                bridges: {
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
                                interfaces: {
                                    type: "array",
                                    uniqueItems: true,
                                    items: {
                                        type: "string",
                                        enum: ["eth0", "eth1", "eth2"]
                                    }
                                },
                                parameters: {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                        "ageing-time": {
                                            type: "string"
                                        },
                                        "aging-time": {
                                            type: "string"
                                        },
                                        priority: {
                                            type: "integer",
                                            minimum: 0,
                                            maximum: 65535
                                        },
                                        "port-priority": {
                                            type: "object",
                                            additionalProperties: false,
                                            properties: {
                                                eth0: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 63
                                                },
                                                eth1: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 63
                                                },
                                                eth2: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 63
                                                },
                                            }
                                        },
                                        "forward-delay": {
                                            type: "string"
                                        },
                                        "hello-time": {
                                            type: "string"
                                        },
                                        "max-age": {
                                            type: "string"
                                        },
                                        "path-cost": {
                                            type: "object",
                                            additionalProperties: false,
                                            properties: {
                                                eth0: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 4000000000
                                                },
                                                eth1: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 4000000000
                                                },
                                                eth2: {
                                                    type: "integer",
                                                    minimum: 0,
                                                    maximum: 4000000000
                                                },
                                            }
                                        },
                                        stp: {
                                            type: "boolean"
                                        }
                                    }
                                },
                                ...common.networkmanager_settings,
                                ...common.openvswitch_bridge_extras
                            },
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["ethernets", "bridges"]
        }
    }
}

export default bridges_schema;
