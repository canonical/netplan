#pragma once

#include <stdio.h>

#include "types.h"
#include "netplan.h"
#include "parse.h"

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
