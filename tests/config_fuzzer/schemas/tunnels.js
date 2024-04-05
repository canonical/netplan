import * as common from "./common.js";

export const wireguard_schema = {
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
                tunnels: {
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
                                addresses: {
                                    type: "array",
                                    items: {
                                        type: "string",
                                        faker: "ipv4_or_ipv6.withprefix"
                                    }
                                },
                                mode: {
                                    type: "string",
                                    enum: ["wireguard"]
                                },
                                key: {
                                    type: "string",
                                    enum: ["rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc="]
                                },
                                port: {
                                    type: "integer",
                                    minimum: 1,
                                    maximum: 65535
                                },
                                peers: {
                                    type: "array",
                                    items: {
                                        type: "object",
                                        additionalProperties: false,
                                        properties: {
                                            endpoint: {
                                                type: "string",
                                                faker: "ipv4_or_ipv6.withport"
                                            },
                                            keepalive: {
                                                type: "integer",
                                                minimum: 0,
                                                maximum: 65535
                                            },
                                            "allowed-ips": {
                                                type: "array",
                                                items: {
                                                    type: "string",
                                                    faker: "ipv4_or_ipv6.withprefix"
                                                }
                                            },
                                            keys: {
                                                type: "object",
                                                additionalProperties: false,
                                                properties: {
                                                    public: {

                                                        type: "string",
                                                        enum: ["M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4="]

                                                    },
                                                    shared: {
                                                        type: "string",
                                                        enum: ["rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc="]
                                                    },
                                                },
                                                required: ["public"]
                                            }
                                        },
                                        required: ["keys", "allowed-ips"]
                                    }
                                },
                                ...common.networkmanager_settings,
                            },
                            required: ["mode", "key", "peers"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["tunnels", "ethernets"]
        }
    }
}

export const sit_schema = {
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
                tunnels: {
                    type: "object",
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
                                addresses: {
                                    type: "array",
                                    items: {
                                        type: "string",
                                        faker: "ipv4_or_ipv6.withprefix"
                                    }
                                },
                                mode: {
                                    type: "string",
                                    enum: ["sit"]
                                },
                                remote: {
                                    type: "string",
                                    faker: "internet.ipv4"
                                },
                                local: {
                                    type: "string",
                                    faker: "internet.ipv4"
                                },
                                addresses: {
                                    type: "array",
                                    items: {
                                        type: "string",
                                        faker: "ipv6.withprefix",
                                    },
                                },
                                ...common.routes
                            },
                            required: ["mode", "remote", "local"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["tunnels"]
        }
    }
}

export const vxlan_schema = {
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
                        }
                    },
                    required: ["eth0"]
                },
                tunnels: {
                    type: "object",
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
                                mode: {
                                    type: "string",
                                    enum: ["vxlan"]
                                },
                                id: {
                                    type: "integer",
                                    minimum: 1,
                                    maximum: 16777215
                                },
                                link: {
                                    type: "string",
                                    enum: ["eth0"]
                                },
                                local: {
                                    type: "string",
                                    faker: "internet.ipv4"
                                },
                                mtu: {
                                    type: "integer",
                                    minimum: 1
                                },
                                "accept-ra": {
                                    type: "boolean"
                                },
                                "neigh-suppress": {
                                    type: "boolean"
                                },
                                "mac-learning": {
                                    type: "boolean"
                                },
                                port: {
                                    type: "integer",
                                    minimum: 0,
                                    maximum: 65535
                                }
                            },
                            required: ["mode", "id", "local"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["tunnels", "ethernets"]
        }
    }
}

export default wireguard_schema;
