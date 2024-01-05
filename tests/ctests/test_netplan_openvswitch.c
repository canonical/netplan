#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "util-internal.h"
#include "validation.h"

#include "test_utils.h"

void
test_write_ovs_bond_interfaces_null_bridge(__unused void** state)
{

    NetplanNetDefinition* netdef = g_malloc0(sizeof(NetplanNetDefinition));

    netdef->bridge = NULL;
    assert_null(write_ovs_bond_interfaces(NULL, netdef, NULL, NULL));

    g_free(netdef);
}

void
test_validate_ovs_target(__unused void** state)
{
    assert_true(validate_ovs_target(TRUE, "10.2.3.4:12345"));
    assert_true(validate_ovs_target(TRUE, "10.2.3.4"));
    assert_true(validate_ovs_target(TRUE, "[::1]:12345"));
    assert_true(validate_ovs_target(TRUE, "[::1]"));

    assert_true(validate_ovs_target(FALSE, "12345:10.2.3.4"));
    assert_true(validate_ovs_target(FALSE, "12345:[::1]"));
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
        cmocka_unit_test(test_validate_ovs_target),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
