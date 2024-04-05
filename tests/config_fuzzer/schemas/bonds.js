import * as common from "./common.js";

const bonds_schema = {
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
                        "eth10": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth11": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth12": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth13": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth14": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth15": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                        "eth16": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                "dhcp4": {
                                    type: "boolean"
                                }
                            }
                        },
                    },
                    required: ["eth10", "eth11", "eth12", "eth13", "eth14", "eth15", "eth16"]
                },
                bonds: {
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
                                        enum: ["eth10", "eth11", "eth12"]
                                    }
                                },
                                parameters: {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                        "mode": {
                                            type: "string",
                                            enum: ["balance-rr", "active-backup", "balance-xor",
                                            "broadcast", "802.3ad", "balance-tlb", "balance-alb"]
                                        },
                                        "lacp-rate": {
                                            type: "string",
                                            enum: ["fast", "slow"]
                                        },
                                        "mii-monitor-interval": {
                                            type: "integer",
                                            minimum: 0,
                                        },
                                        "min-links": {
                                            type: "integer",
                                            minimum: 0
                                        },
                                        "transmit-hash-policy": {
                                            type: "string",
                                            enum: ["layer2", "layer3+4", "layer2+3", "encap2+3", "encap3+4"]
                                        },
                                        "ad-select": {
                                            type: "string",
                                            enum: ["stable", "bandwidth", "count"]
                                        },
                                        "all-members-active": {
                                            type: "boolean"
                                        },
                                        "arp-interval": {
                                            type: "integer",
                                            minimum: 0
                                        },
                                        "arp-ip-targets": {
                                            type: "array",
                                            items: {
                                                type: "string",
                                                faker: "internet.ipv4"
                                            }
                                        },
                                        "arp-validate": {
                                            type: "string",
                                            enum: ["none", "active", "backup", "all"]
                                        },
                                        "arp-all-targets": {
                                            type: "string",
                                            enum: ["any", "all"]
                                        },
                                        "up-delay": {
                                            type: "integer",
                                            minimum: 0
                                        },
                                        "down-delay": {
                                            type: "integer",
                                            minimum: 0
                                        },
                                        "fail-over-mac-policy": {
                                            type: "string",
                                            enum: ["none", "active", "follow"]
                                        },
                                        "gratuitous-arp": {
                                            type: "integer",
                                            minimum: 0,
                                            maximum: 255
                                        },
                                        "packets-per-member": {
                                            type: "integer",
                                            minimum: 0
                                        },
                                        "primary-reselect-policy": {
                                            type: "string",
                                            enum: ["always", "better", "failure"]
                                        },
                                        "resend-igmp": {
                                            type: "integer",
                                            minimum: 0,
                                            maximum: 255
                                        },
                                        "learn-packet-interval": {
                                            type: "integer",
                                            minimum: 1,
                                            maximum: 0x7fffffff
                                        },
                                        primary: {
                                            type: "string",
                                            enum: ["eth10", "eth11", "eth12"]
                                        },
                                    },
                                    ...common.networkmanager_settings,
                                }
                            },
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["bonds", "ethernets"]
        }
    }
}


export default bonds_schema;
