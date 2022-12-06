#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "../../include/netplan.h"
#include "../../include/parse.h"
#include "types-internal.h"
#include "types.h"

#undef __USE_MISC
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

void
test_netplan_netdef_get_output_filename_nm_with_ssid(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "run/NetworkManager/system-connections/netplan-enlol3s0-home-network.nmconnection";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NM;
    netdef.id = "enlol3s0";
    const char* ssid = "home-network";

    size_t ret = netplan_netdef_get_output_filename(&netdef, ssid, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, expected_size);
    assert_string_equal(out_buffer, expected);
}

void
test_netplan_netdef_get_output_filename_nm_without_ssid(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "run/NetworkManager/system-connections/netplan-enlol3s0.nmconnection";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NM;
    netdef.id = "enlol3s0";

    size_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, expected_size);
    assert_string_equal(out_buffer, expected);
}

void
test_netplan_netdef_get_output_filename_networkd(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "run/systemd/network/10-netplan-enlol3s0.network";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NETWORKD;
    netdef.id = "enlol3s0";

    size_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, expected_size);
    assert_string_equal(out_buffer, expected);
}

void
test_netplan_netdef_get_output_filename_buffer_is_too_small(void** state)
{
    NetplanNetDefinition netdef;
    char out_buffer[16] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NETWORKD;
    netdef.id = "enlol3s0";

    size_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, NETPLAN_BUFFER_TOO_SMALL);
}

void
test_netplan_netdef_get_output_filename_invalid_backend(void** state)
{
    NetplanNetDefinition netdef;
    char out_buffer[16] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NONE;
    netdef.id = "enlol3s0";

    size_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, 0);
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
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_no_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_with_ssid),
           cmocka_unit_test(test_netplan_get_id_from_nm_filename_filename_is_malformed),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_nm_with_ssid),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_nm_without_ssid),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_networkd),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_buffer_is_too_small),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_invalid_backend),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
