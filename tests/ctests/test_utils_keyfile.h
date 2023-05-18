#pragma once

#include <stdio.h>
#include <sys/mman.h>

#include "types.h"
#include "netplan.h"
#include "parse.h"
#include "parse-nm.h"
#include "util.h"
#include "types-internal.h"

// LCOV_EXCL_START
NetplanState*
load_keyfile_string_to_netplan_state(const char* keyfile)
{
    NetplanError** error = NULL;
    NetplanState* np_state = NULL;

    NetplanParser* npp = netplan_parser_new();

    int fd = memfd_create("keyfile.nmconnection", 0);

    char* ptr = (char*) keyfile;
    while (*ptr) {
        if (write(fd, ptr, 1) <= 0) break;
        ptr++;
    }

    g_autofree gchar* path = g_strdup_printf("/proc/self/fd/%d", fd);
    netplan_parser_load_keyfile(npp, path, error);
    if (error && *error) {
        netplan_error_clear(error);
    } else {
        np_state = netplan_state_new();
        netplan_state_import_parser_results(np_state, npp, error);
    }

    netplan_parser_clear(&npp);

    if (error && *error) {
        netplan_state_clear(&np_state);
    }

    return np_state;
}

// LCOV_EXCL_STOP
