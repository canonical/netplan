#include "state.h"
#include <stdio.h>

#include <types.h>
#include <netplan.h>
#include <parse-nm.h>
#include <parse.h>
#include <util.h>


int main(int argc, char** argv) {
    NetplanParser *npp;
    NetplanState *np_state;
    NetplanError* error = NULL;

    if (argc < 2) return 1;

    npp = netplan_parser_new();

    netplan_parser_load_keyfile(npp, argv[1], &error);
    if (error) goto exit_parser;

    np_state = netplan_state_new();

    netplan_state_import_parser_results(np_state, npp, &error);
    if (error) goto exit_state;

    int stdout_fd = fileno(stdout);
    netplan_state_dump_yaml(np_state, stdout_fd, &error);
    if (error) {
        printf("state_dump_yaml failed\n");
        goto exit_state;
    }

    netplan_state_clear(&np_state);
    netplan_parser_clear(&npp);
    if (error) netplan_error_clear(&error);
    return 0;

exit_state:
    netplan_state_clear(&np_state);

exit_parser:
    netplan_parser_clear(&npp);
    if (error) netplan_error_clear(&error);

    return 1;
}
