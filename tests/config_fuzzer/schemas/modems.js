import * as common from "./common.js";

const modems_schema = {
    type: "object",
    additionalProperties: false,
    properties: {
        network: {
            type: "object",
            additionalProperties: false,
            properties: {
                renderer: {
                    type: "string",
                    enum: ["NetworkManager"]
                },
                version: {
                    type: "integer",
                    minimum: 2,
                    maximum: 2
                },
                modems: {
                    type: "object",
                    ...common.minMaxProperties,
                    properties: {
                        renderer: {
                            type: "string",
                            enum: ["NetworkManager"]
                        },
                    },
                    patternProperties: {
                        "[azAZ09-]{1,15}": {
                            additionalProperties: false,
                            properties: {
                                renderer: {
                                    type: "string",
                                    enum: ["NetworkManager"]
                                },
                                mtu: {
                                    type: "integer",
                                    minimum: 0
                                },
                                apn: {
                                    type: "string"
                                },
                                username: {
                                    type: "string",
                                    faker: "internet.email"
                                },
                                password: {
                                    type: "string"
                                },
                                number: {
                                    type: "integer"
                                },
                                "network-id": {
                                    type: "string"
                                },
                                "device-id": {
                                    type: "string"
                                },
                                pin: {
                                    type: "integer"
                                },
                                "sim-id": {
                                    type: "integer"
                                },
                                "sim-operator-id": {
                                    type: "integer"
                                },
                                ...common.networkmanager_settings,
                            },
                            required: ["renderer"]
                        }
                    },
                    required: ["[azAZ09-]{1,15}"]
                },
            },
            required: ["modems"]
        }
    }
}


export default modems_schema;
