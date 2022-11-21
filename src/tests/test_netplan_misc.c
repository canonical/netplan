#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "../../include/netplan.h"
#include "../../include/parse.h"

#undef __USE_MISC
#include "../error.c"
#include "../names.c"
#include "../validation.c"
#include "../types.c"
#include "../util.c"
#include "../parse.c"

void
test_netplan_get_optional(void** state) {

    const char* filename = FIXTURESDIR "/optional.yaml";
    GError *error = NULL;
    NetplanParser *npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);
    netplan_error_free(&error);

    assert_true(res);

    NetplanState *np_state = netplan_state_new();
    res = netplan_state_import_parser_results(np_state, npp, &error);
    netplan_error_free(&error);
    assert_true(res);

    NetplanNetDefinition* interface = g_hash_table_lookup(np_state->netdefs, "eth0");
    gboolean optional = _netplan_netdef_get_optional(interface);

    assert_true(optional);

    netplan_state_clear(&np_state);
    netplan_parser_clear(&npp);
}

int setup(void** state) {
    return 0;
}

int tear_down(void** state) {
    return 0;
}

int main() {

       const struct CMUnitTest tests[] = {
           cmocka_unit_test(test_netplan_get_optional),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
