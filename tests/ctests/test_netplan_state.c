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

void test_netplan_state_new_state(void** state) {
    NetplanState* np_state = netplan_state_new();
    assert_non_null(np_state);
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
        cmocka_unit_test(test_netplan_state_new_state),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
