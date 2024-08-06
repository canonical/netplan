#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse.h"
#include "util.h"
#include "util-internal.h"

void
test_netplan_error_message(__unused void** state)
{
    const gchar* message = "it failed";
    char error_message[100] = {0};
    GError *gerror = g_error_new(1, 2, "%s: error message", message);
    netplan_error_message(gerror, error_message, sizeof(error_message) - 1);
    assert_string_equal(error_message, "it failed: error message");
    netplan_error_clear(&gerror);
}

void
test_netplan_error_code(__unused void** state)
{
    GError *gerror = g_error_new(1234, 5678, "%s: error message", "it failed");
    uint64_t error_code = netplan_error_code(gerror);
    GQuark domain = (GQuark)(error_code >> 32);
    gint error = (gint) error_code;

    assert_int_equal(domain, 1234);
    assert_int_equal(error, 5678);
    netplan_error_clear(&gerror);
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
        cmocka_unit_test(test_netplan_error_message),
        cmocka_unit_test(test_netplan_error_code),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
