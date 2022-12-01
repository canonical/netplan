#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "../../include/netplan.h"
#include "../../include/parse.h"

#undef __USE_MISC
#include "error.c"
#include "names.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"

#include "test_utils.h"

void
test_netplan_get_optional(void** state) {

    NetplanState* np_state = load_fixture_to_netplan_state("optional.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eth0");
    gboolean optional = _netplan_netdef_get_optional(interface);

    assert_true(optional);

    netplan_state_clear(&np_state);
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
