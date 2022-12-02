#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "../../include/netplan.h"
#include "../../include/parse.h"
#include "types.h"

#undef __USE_MISC
#include "error.c"
#include "names.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"

#include "test_utils.h"

void
test_netplan_get_optional(void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("optional.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eth0");
    gboolean optional = _netplan_netdef_get_optional(interface);

    assert_true(optional);

    netplan_state_clear(&np_state);
}

void
test_netplan_get_id_from_nm_filepath_no_ssid(void **state)
{

    const char* filename = "/some/rootdir/run/NetworkManager/system-connections/netplan-some-id.nmconnection";
    char id[16];

    ssize_t bytes_copied = netplan_get_id_from_nm_filepath(filename, NULL, id, sizeof(id));

    assert_string_equal(id, "some-id");
    assert_int_equal(bytes_copied, 8); // size of some-id + null byte
}

void
test_netplan_get_id_from_nm_filepath_with_ssid(void **state)
{

    const char* filename = "/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection";
    char id[16];

    ssize_t bytes_copied = netplan_get_id_from_nm_filepath(filename, "SOME-SSID", id, sizeof(id));

    assert_string_equal(id, "some-id");
    assert_int_equal(bytes_copied, 8); // size of some-id + null byte
}

void
test_netplan_get_id_from_nm_filepath_buffer_is_too_small(void **state)
{

    const char* filename = "/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection";
    char id[7];

    ssize_t bytes_copied = netplan_get_id_from_nm_filepath(filename, "SOME-SSID", id, sizeof(id));

    assert_int_equal(bytes_copied, NETPLAN_BUFFER_TOO_SMALL);
}

void
test_netplan_get_id_from_nm_filepath_buffer_is_the_exact_size(void **state)
{

    const char* filename = "/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection";
    char id[8];

    ssize_t bytes_copied = netplan_get_id_from_nm_filepath(filename, "SOME-SSID", id, sizeof(id));

    assert_string_equal(id, "some-id");
    assert_int_equal(bytes_copied, 8); // size of some-id + null byte
}

void
test_netplan_get_id_from_nm_filepath_filename_is_malformed(void **state)
{

    const char* filename = "INVALID/netplan-some-id.nmconnection";
    char id[8];

    ssize_t bytes_copied = netplan_get_id_from_nm_filepath(filename, "SOME-SSID", id, sizeof(id));

    assert_int_equal(bytes_copied, 0);
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
           cmocka_unit_test(test_netplan_get_optional),
           cmocka_unit_test(test_netplan_get_id_from_nm_filepath_no_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filepath_with_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filepath_buffer_is_too_small),
           cmocka_unit_test(test_netplan_get_id_from_nm_filepath_buffer_is_the_exact_size),
           cmocka_unit_test(test_netplan_get_id_from_nm_filepath_filename_is_malformed),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
