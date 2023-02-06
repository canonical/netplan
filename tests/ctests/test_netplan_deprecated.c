#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse.h"
#include "types-internal.h"
#include "types.h"

#include "error.c"
#include "names.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"
#include "netplan.c"

// LCOV_EXCL_START
gboolean
netplan_parser_load_keyfile(NetplanParser* npp, const char* filename, NetplanError** error)
{
    return 1; //
}
// LCOV_EXCL_STOP

#include "abi_compat.c"

#include "test_utils.h"

void
test_netplan_get_id_from_nm_filename_no_ssid(void **state)
{
    const char* filename = "/some/rootdir/run/NetworkManager/system-connections/netplan-some-id.nmconnection";
    char* id = netplan_get_id_from_nm_filename(filename, NULL);
    assert_string_equal(id, "some-id");
    g_free(id);
}

void
test_netplan_get_id_from_nm_filename_with_ssid(void **state)
{
    const char* filename = "/some/rootdir/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection";
    char* id = netplan_get_id_from_nm_filename(filename, "SOME-SSID");
    assert_string_equal(id, "some-id");
    g_free(id);
}

void
test_netplan_get_id_from_nm_filename_filename_is_malformed(void **state)
{
    const char* filename = "INVALID/netplan-some-id.nmconnection";
    char* id = netplan_get_id_from_nm_filename(filename, NULL);
    assert_null(id);
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
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_no_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_with_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_filename_is_malformed),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
