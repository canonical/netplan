#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse.h"
#include "util-internal.h"

#include "test_utils.h"

void
test_netplan_state_new_state(__unused void** state)
{
    NetplanState* np_state = netplan_state_new();
    assert_non_null(np_state);
    netplan_state_clear(&np_state);
}

void
test_netplan_state_iterator(__unused void** state)
{
    NetplanState* np_state = load_fixture_to_netplan_state("bond.yaml");
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    assert_true(netplan_state_iterator_has_next(&iter));
    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "eth0");

    assert_true(netplan_state_iterator_has_next(&iter));
    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "bond0");

    assert_false(netplan_state_iterator_has_next(&iter));
    netdef = netplan_state_iterator_next(&iter);
    assert_null(netdef);

    netplan_state_clear(&np_state);
}

void
test_netplan_state_iterator_empty(__unused void** state)
{
    NetplanStateIterator iter = { 0 };
    NetplanNetDefinition* netdef = NULL;

    netdef = netplan_state_iterator_next(&iter);
    assert_null(netdef);
}

void
test_netplan_state_iterator_null(__unused void** state)
{
    NetplanStateIterator *iter = NULL;
    NetplanNetDefinition* netdef = NULL;

    netdef = netplan_state_iterator_next(iter);
    assert_null(netdef);
}

void
test_netplan_state_iterator_null_has_next(__unused void** state)
{
    assert_false(netplan_state_iterator_has_next(NULL));
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
        cmocka_unit_test(test_netplan_state_new_state),
        cmocka_unit_test(test_netplan_state_iterator),
        cmocka_unit_test(test_netplan_state_iterator_empty),
        cmocka_unit_test(test_netplan_state_iterator_null),
        cmocka_unit_test(test_netplan_state_iterator_null_has_next),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
