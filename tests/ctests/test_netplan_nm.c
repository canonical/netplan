#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "util-internal.h"

#include "test_utils.h"

/* Trying to write an empty netplan_state should return True without
* actually writing anything.
*/
void
test_write_empty_state(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  renderer: NetworkManager\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);

    assert_true(netplan_state_finish_nm_write(np_state, NULL, NULL));

    netplan_state_clear(&np_state);
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
        cmocka_unit_test(test_write_empty_state),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
