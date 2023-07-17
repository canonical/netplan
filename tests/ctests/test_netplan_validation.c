#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse.h"

#include "error.c"
#include "names.c"
#include "netplan.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"

#include "test_utils.h"

void
test_validate_interface_name_length(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  bridges:\n"
        "    ashortname:\n"
        "      dhcp4: no\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    assert_true(validate_interface_name_length(netdef));

    netplan_state_clear(&np_state);
}

void
test_validate_interface_name_length_set_name(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth0:\n"
        "      match:\n"
        "        macaddress: aa:bb:cc:dd:ee:ff\n"
        "      set-name: ashortname\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    assert_true(validate_interface_name_length(netdef));

    netplan_state_clear(&np_state);
}

void
test_validate_interface_name_length_too_long(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  bridges:\n"
        "    averylongnameforaninterface:\n"
        "      dhcp4: no\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    assert_false(validate_interface_name_length(netdef));

    netplan_state_clear(&np_state);
}

void
test_validate_interface_name_length_set_name_too_long(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth0:\n"
        "      match:\n"
        "        macaddress: aa:bb:cc:dd:ee:ff\n"
        "      set-name: averylongnameforaninterface\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    assert_false(validate_interface_name_length(netdef));

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
        cmocka_unit_test(test_validate_interface_name_length),
        cmocka_unit_test(test_validate_interface_name_length_too_long),
        cmocka_unit_test(test_validate_interface_name_length_set_name),
        cmocka_unit_test(test_validate_interface_name_length_set_name_too_long),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
