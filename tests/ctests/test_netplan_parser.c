#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse.h"

#undef __USE_MISC
#include "error.c"
#include "names.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"

#include "test_utils.h"

void
test_netplan_parser_new_parser(void** state)
{
    NetplanParser* npp = netplan_parser_new();
    assert_non_null(npp);
    netplan_parser_clear(&npp);
}

void
test_netplan_parser_load_yaml(void** state)
{
    const char* filename = FIXTURESDIR "/ovs.yaml";
    GError *error = NULL;
    NetplanParser* npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);

    assert_true(res);

    netplan_parser_clear(&npp);
}

void
test_netplan_parser_interface_has_bridge_netdef(void** state)
{

    NetplanState *np_state = load_fixture_to_netplan_state("bridge.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "enp3s0");

    NetplanNetDefinition* bridge = netplan_netdef_get_bridge_link(interface);

    assert_non_null(interface);
    assert_non_null(bridge);

    assert_ptr_equal(interface->bridge_link, bridge);

    netplan_state_clear(&np_state);

}

void
test_netplan_parser_interface_has_bond_netdef(void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("bond.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eth0");

    NetplanNetDefinition* bond = netplan_netdef_get_bond_link(interface);

    assert_non_null(interface);
    assert_non_null(bond);

    assert_ptr_equal(interface->bond_link, bond);

    netplan_state_clear(&np_state);

}

void
test_netplan_parser_interface_has_peer_netdef(void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("ovs.yaml");

    NetplanNetDefinition* patch0 = netplan_state_get_netdef(np_state, "patch0-1");

    NetplanNetDefinition* patch1 = netplan_netdef_get_peer_link(patch0);
    patch0 = netplan_netdef_get_peer_link(patch1);

    assert_non_null(patch0);
    assert_non_null(patch1);

    assert_ptr_equal(patch0->peer_link, patch1);
    assert_ptr_equal(patch1->peer_link, patch0);

    netplan_state_clear(&np_state);
}

void
test_netplan_parser_sriov_embedded_switch(void** state)
{

    char embedded_switch[16];

    NetplanState* np_state = load_fixture_to_netplan_state("sriov.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eno1");

    _netplan_netdef_get_embedded_switch_mode(interface, embedded_switch, sizeof(embedded_switch) - 1);

    assert_string_equal(embedded_switch, "switchdev");

    netplan_state_clear(&np_state);
}

void
test_netplan_parser_sriov_vf_count(void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("sriov.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eno1");

    guint count = _netplan_netdef_get_vf_count(interface);

    assert_int_equal(count, 2);

    netplan_state_clear(&np_state);

}

int
setup(void** state)
{
    return 0;
}

int
tear_down(void** state)
{
    return 0;
}

int
main()
{

       const struct CMUnitTest tests[] = {
           cmocka_unit_test(test_netplan_parser_new_parser),
           cmocka_unit_test(test_netplan_parser_load_yaml),
           cmocka_unit_test(test_netplan_parser_interface_has_bridge_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_bond_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_peer_netdef),
           cmocka_unit_test(test_netplan_parser_sriov_embedded_switch),
           cmocka_unit_test(test_netplan_parser_sriov_vf_count),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
