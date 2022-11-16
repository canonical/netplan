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

void test_netplan_parser_new_parser(void** state) {
    NetplanParser* npp = netplan_parser_new();
    assert_non_null(npp);
    netplan_parser_clear(&npp);
}

void test_netplan_parser_load_yaml(void** state) {
    const char* filename = FIXTURESDIR "/ovs.yaml";
    GError *error = NULL;
    NetplanParser* npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);

    assert_true(res);

    netplan_error_free(&error);
    netplan_parser_clear(&npp);
}

void
test_netplan_parser_interface_has_bridge_netdef(void** state) {

    const char* filename = FIXTURESDIR "/bridge.yaml";
    GError *error = NULL;
    NetplanParser *npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);
    netplan_error_free(&error);

    assert_true(res);

    NetplanState *np_state = netplan_state_new();
    res = netplan_state_import_parser_results(np_state, npp, &error);
    netplan_error_free(&error);
    assert_true(res);

    NetplanNetDefinition* interface = g_hash_table_lookup(np_state->netdefs, "enp3s0");

    NetplanNetDefinition* bridge = netplan_netdef_get_bridge_link(interface);

    assert_non_null(interface);
    assert_non_null(bridge);

    assert_ptr_equal(interface->bridge_link, bridge);

    netplan_state_clear(&np_state);
    netplan_parser_clear(&npp);

}

void
test_netplan_parser_interface_has_bond_netdef(void** state) {

    const char* filename = FIXTURESDIR "/bond.yaml";
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

    NetplanNetDefinition* bond = netplan_netdef_get_bond_link(interface);

    assert_non_null(interface);
    assert_non_null(bond);

    assert_ptr_equal(interface->bond_link, bond);

    netplan_state_clear(&np_state);
    netplan_parser_clear(&npp);

}

void
test_netplan_parser_interface_has_peer_netdef(void** state) {

    const char* filename = FIXTURESDIR "/ovs.yaml";
    GError *error = NULL;
    NetplanParser *npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);
    netplan_error_free(&error);

    assert_true(res);

    NetplanState *np_state = netplan_state_new();
    res = netplan_state_import_parser_results(np_state, npp, &error);
    netplan_error_free(&error);
    assert_true(res);

    NetplanNetDefinition* patch0 = g_hash_table_lookup(np_state->netdefs, "patch0-1");

    NetplanNetDefinition* patch1 = netplan_netdef_get_peer_link(patch0);
    patch0 = netplan_netdef_get_peer_link(patch1);

    assert_non_null(patch0);
    assert_non_null(patch1);

    assert_ptr_equal(patch0->peer_link, patch1);
    assert_ptr_equal(patch1->peer_link, patch0);

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
           cmocka_unit_test(test_netplan_parser_new_parser),
           cmocka_unit_test(test_netplan_parser_load_yaml),
           cmocka_unit_test(test_netplan_parser_interface_has_bridge_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_bond_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_peer_netdef),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
