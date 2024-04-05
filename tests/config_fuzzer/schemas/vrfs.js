import * as common from "./common.js";

const vrfs_schema = {
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
                vrfs: {
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
                                table: {
                                    type: "integer",
                                    minimum: 100,
                                    maximum: 100
                                },
                                interfaces: {
                                    type: "array",
                                    uniqueItems: true,
                                    items: {
                                        type: "string",
                                        enum: ["eth0", "eth1", "eth2"]
                                    }
                                },
                                routes: {
                                    type: "array",
                                    items: {
                                        type: "object",
                                        additionalProperties: false,
                                        properties: {
                                            from: {
                                                type: "string",
                                                faker: "ipv4.withprefix"
                                            },
                                            to: {
                                                type: "string",
                                                faker: "ipv4.withprefix"
                                            },
                                            via: {
                                                type: "string",
                                                faker: "internet.ipv4"
                                            },
                                            "on-link": {
                                                type: "boolean"
                                            },
                                            metric: {
                                                type: "integer",
                                                minimum: 0
                                            },
                                            type: {
                                                type: "string",
                                                enum: ["unicast", "anycast", "blackhole", "broadcast", "local", "multicast", "nat", "prohibit", "throw", "unreachable", "xresolve"]
                                            },
                                            scope: {
                                                type: "string",
                                                enum: ["global", "link", "host"]
                                            },
                                            table: {
                                                type: "integer",
                                                minimum: 100,
                                                maximum: 100
                                            },
                                            mtu: {
                                                type: "integer",
                                                minimum: 0
                                            },
                                            "congestion-window": {
                                                type: "integer",
                                                minimum: 0
                                            },
                                            "advertised-receive-window": {
                                                type: "integer",
                                                minimum: 0
                                            }
                            
                                        },
                                        required: ["to", "via"]
                                    }
                                },
                                "routing-policy": {
                                    type: "array",
                                    items: {
                                        type: "object",
                                        additionalProperties: false,
                                        properties: {
                                            from: {
                                                type: "string",
                                                faker: "ipv4.withprefix"
                                            },
                                            to: {
                                                type: "string",
                                                faker: "ipv4.withprefix"
                                            },
                                            table: {
                                                type: "integer",
                                                minimum: 100,
                                                maximum: 100
                                            },
                                            priority: {
                                                type: "integer",
                                                minimum: 0,
                                            },
                                            mark: {
                                                type: "integer",
                                                minimum: 0,
                                            },
                                            "type-of-service": {
                                                type: "integer",
                                                minimum: 0,
                                                maximum: 255
                                            }
                                        },
                                        required: ["to", "via"],
                                    }
                                },
                                ...common.networkmanager_settings,
                            },
                            required: ["table"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["vrfs", "ethernets"]
        }
    }
}


export default vrfs_schema;
