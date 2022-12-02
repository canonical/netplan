#pragma once

#include <stdio.h>

#include "types.h"
#include "netplan.h"
#include "parse.h"

NetplanState *
load_fixture_to_netplan_state(const char* filename)
{

    GError *error = NULL;

    int path_size = strlen(FIXTURESDIR) + strlen(filename) + 2;
    char* filepath = calloc(path_size, 1);

    snprintf(filepath, path_size, "%s/%s", FIXTURESDIR, filename);

    NetplanParser *npp = netplan_parser_new();
    netplan_parser_load_yaml(npp, filepath, &error);

    NetplanState *np_state = netplan_state_new();
    netplan_state_import_parser_results(np_state, npp, &error);

    netplan_parser_clear(&npp);
    free(filepath);

    return np_state;
}
