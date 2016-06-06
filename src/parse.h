#pragma once

/****************************************************
 * Parsed definitions
 ****************************************************/

typedef enum {
    ND_NONE,
    ND_ETHERNET,
} netdef_type;

/**
 * Represent one configuration stanza in "network". This is a linked list, so
 * that composite devices like bridges can refer to previous definitions as
 * components */
typedef struct net_definition {
    netdef_type type;
    char* id;
    char* set_name;
    gboolean wake_on_lan;
    struct {
        char* driver;
        char* mac;
    } match;

    /* singly-linked list */
    struct net_definition *prev;
} net_definition;

/* Written/updated by parse_yaml() */
extern net_definition *netdefs;

/****************************************************
 * Functions
 ****************************************************/

gboolean parse_yaml(const char* filename, GError **error);
