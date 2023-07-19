#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"

#include "error.c"
#include "names.c"
#include "netplan.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"
#include "networkd.c"
#include "openvswitch.c"

#include "test_utils.h"

void
test_write_ovs_bond_interfaces_null_bridge(__unused void** state)
{

    NetplanNetDefinition* netdef = g_malloc0(sizeof(NetplanNetDefinition));

    netdef->bridge = NULL;
    assert_null(write_ovs_bond_interfaces(NULL, netdef, NULL, NULL));

    g_free(netdef);
}


int
setup(__unused void** state)
{
    return 0;
}

int
tear_down(__unused void** state)
{
    return 0;
}

int
main()
{

    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_write_ovs_bond_interfaces_null_bridge),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
