export const minMaxProperties = {
    minProperties: 3,
    maxProperties: 10,
};

export const routes = {
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
                    minimum: 0
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
                },
                "advertised-mss": {
                    type: "integer",
                    minimum: 0
                }
            },
            required: ["to", "via"]
        }
    }
};
export const routing_policy = {
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
                    minimum: 0,
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
    }
};

export const common_properties = {
    dhcp4: {
        type: "boolean"
    },
    dhcp6: {
        type: "boolean"
    },
    critical: {
        type: "boolean"
    },
    "dhcp-identifier": {
        type: "string",
        enum: ["duid", "mac"]
    },
    "accept-ra": {
        type: "boolean"
    },
    gateway4: {
        type: "string",
        faker: "internet.ipv4"
    },
    gateway6: {
        type: "string",
        faker: "internet.ipv6"
    },
    addresses: {
        type: "array",
        items: {
            anyOf: [
                {
                    type: "string",
                    faker: "ipv4_or_ipv6.withprefix",
                },
                {
                    type: "object",
                    patternProperties: {
                        "192\\.168\\.[1-9]{2}\\.0/24": {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                                lifetime: {
                                    type: "string",
                                    enum: ["forever", 0]
                                },
                                label: {
                                    type: "string",
                                    maxLength: 15,
                                }
                            }
                        }
                    }
                }
            ]
        }
    },
    nameservers: {
        type: "object",
        additionalProperties: false,
        properties: {
            search: {
                type: "array",
                items: {
                    type: "string",
                    faker: "internet.domainName",
                }
            },
            addresses: {
                type: "array",
                items: {

                    anyOf: [
                        {
                            type: "string",
                            faker: "internet.ipv4",
                            format: "ipv4"
                        },
                        {
                            type: "string",
                            faker: "internet.ipv6",
                            format: "ipv6"
                        }

                    ]
                }
            }
        }
    },
    ...routes,
    ...routing_policy
};

export const networkmanager_settings = {
    networkmanager: {
        type: "object",
        additionalProperties: false,
        properties: {
            uuid: {
                type: "string"
            },
            name: {
                type: "string"
            },
            passthrough: {
                type: "object",
                additionalProperties: true,
                properties: {
                    "connection.type": {
                        type: "string"
                    }
                },
            }
        },
        required: ["passthrough"]
    }
};

export const openvswitch_bond_extras = {
    openvswitch: {
        type: "object",
        additionalProperties: false,
        properties: {
            "external-ids": {
                type: "object"
            },
            "other-config": {
                type: "object"
            },
            lacp: {
                type: "string",
                enum: ["active", "passive", "off"]
            },
        },
        required: ["passthrough"]
    }
};

export const openvswitch_bridge_extras = {
    openvswitch: {
        type: "object",
        additionalProperties: false,
        properties: {
            "external-ids": {
                type: "object"
            },
            "other-config": {
                type: "object"
            },
            "fail-mode": {
                type: "string",
                enum: ["standalone", "secure"]
            },
            "mcast-snooping": {
                type: "boolean"
            },
            rstp: {
                type: "boolean"
            },
            protocols: {
                type: "array",
                items: {
                    type: "string",
                    enum: ["OpenFlow10", "OpenFlow11", "OpenFlow12", "OpenFlow13", "OpenFlow14", "OpenFlow15"]
                }
            },
            "controller": {
                type: "object",
                additionalProperties: false,
                properties: {
                    "addresses": {
                        type: "array",
                        items: {
                            type: "string",
                            faker: "openvswitch.controller_address"
                        }
                    },
                    "connection-mode": {
                        type: "string",
                        enum: ["in-band", "out-of-band"]
                    }

                }
            }
        },
    }
};

export default common_properties;
