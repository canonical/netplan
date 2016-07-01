#pragma once

/****************************************************
 * Parsed definitions
 ****************************************************/

typedef enum {
    ND_NONE,
    /* physical devices */
    ND_ETHERNET,
    ND_WIFI,
    /* virtual devices */
    ND_VIRTUAL,
    ND_BRIDGE = ND_VIRTUAL,
} netdef_type;

typedef enum {
    BACKEND_NONE,
    BACKEND_NETWORKD,
    BACKEND_NM,
} netdef_backend;

/**
 * Represent a configuration stanza
 */
typedef struct net_definition {
    netdef_type type;
    netdef_backend backend;
    char* id;

    gboolean dhcp4;

    char* bridge;

    /* these properties are only valid for physical interfaces (type < ND_VIRTUAL) */
    char* set_name;
    struct {
        char* driver;
        char* mac;
        char* original_name;
    } match;
    gboolean has_match;
    gboolean wake_on_lan;

    /* these properties are only valid for ND_WIFI */
    GHashTable* access_points; /* SSID → wifi_access_point* */
} net_definition;

typedef enum {
    WIFI_MODE_INFRASTRUCTURE,
    WIFI_MODE_ADHOC,
    WIFI_MODE_AP
} wifi_mode;

typedef struct {
    wifi_mode mode;
    char* ssid;
    char* password;
} wifi_access_point;


/* Written/updated by parse_yaml(): char* id →  net_definition */
extern GHashTable* netdefs;

/****************************************************
 * Functions
 ****************************************************/

gboolean parse_yaml(const char* filename, GError** error);
gboolean finish_parse(GError** error);
