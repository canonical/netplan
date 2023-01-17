#pragma once

#include <stdio.h>

#include "types.h"
#include "netplan.h"
#include "parse.h"
#include "util.h"
#include "types-internal.h"

// LCOV_EXCL_START
NetplanState *
load_fixture_to_netplan_state(const char* filename)
{

    g_autoptr(GError) error = NULL;
    g_autofree char* filepath = NULL;

    filepath = g_build_path(G_DIR_SEPARATOR_S, FIXTURESDIR, filename, NULL);

    NetplanParser *npp = netplan_parser_new();
    netplan_parser_load_yaml(npp, filepath, &error);

    NetplanState *np_state = netplan_state_new();
    netplan_state_import_parser_results(np_state, npp, &error);

    netplan_parser_clear(&npp);

    return np_state;
}

NetplanState*
load_string_to_netplan_state(const char* yaml)
{
    yaml_parser_t parser;
    yaml_document_t* doc;
    NetplanError** error = NULL;
    NetplanState* np_state = NULL;

    NetplanParser* npp = netplan_parser_new();

    doc = &npp->doc;

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_string(&parser, (const unsigned char*) yaml, strlen(yaml));
    yaml_parser_load(&parser, doc);

    process_document(npp, error);

    if (error && *error) {
        netplan_error_free(*error);
    } else {
        np_state = netplan_state_new();
        netplan_state_import_parser_results(np_state, npp, error);
    }

    yaml_parser_delete(&parser);
    yaml_document_delete(doc);
    netplan_parser_clear(&npp);

    if (error && *error) {
        netplan_state_clear(&np_state);
    }

    return np_state;
}

// LCOV_EXCL_STOP
