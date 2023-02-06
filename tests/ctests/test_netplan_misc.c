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
test_netplan_netdef_get_output_filename_nm_with_ssid(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "/run/NetworkManager/system-connections/netplan-enlol3s0-home-network.nmconnection";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NM;
    netdef.id = "enlol3s0";
    const char* ssid = "home-network";

    ssize_t ret = netplan_netdef_get_output_filename(&netdef, ssid, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, expected_size);
    assert_string_equal(out_buffer, expected);
}

void
test_netplan_netdef_get_output_filename_nm_without_ssid(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "/run/NetworkManager/system-connections/netplan-enlol3s0.nmconnection";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NM;
    netdef.id = "enlol3s0";

    ssize_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, expected_size);
    assert_string_equal(out_buffer, expected);
}

void
test_netplan_netdef_get_output_filename_networkd(void** state)
{
    NetplanNetDefinition netdef;
    const char* expected = "/run/systemd/network/10-netplan-enlol3s0.network";
    size_t expected_size = strlen(expected) + 1;
    char out_buffer[100] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NETWORKD;
    netdef.id = "enlol3s0";

    ssize_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

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

    ssize_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, NETPLAN_BUFFER_TOO_SMALL);
}

void
test_netplan_netdef_get_output_filename_invalid_backend(void** state)
{
    NetplanNetDefinition netdef;
    char out_buffer[16] = { 0 };

    netdef.backend = NETPLAN_BACKEND_NONE;
    netdef.id = "enlol3s0";

    ssize_t ret = netplan_netdef_get_output_filename(&netdef, NULL, out_buffer, sizeof(out_buffer) - 1);

    assert_int_equal(ret, 0);
}

void
test_util_is_route_present(void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth0:\n"
        "      routing-policy:\n"
        "        - from: 10.0.0.1\n"
        "          table: 1001\n"
        "        - from: 10.0.0.2\n"
        "          table: 1002\n"
        "      routes:\n"
        "        - to: 0.0.0.0/0\n"
        "          via: 10.0.0.200\n"
        "          table: 1002\n"
        "        - to: 0.0.0.0/0\n"
        "          via: 10.0.0.200\n"
        "          table: 1001\n"
        "        - to: 192.168.0.0/24\n"
        "          via: 10.20.30.40\n"
        "        - to: 192.168.0.0/24\n"
        "          scope: link\n"
        "        - to: default\n"
        "          via: abcd::1\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    NetplanIPRoute* route = g_new0(NetplanIPRoute, 1);
    route->family = AF_INET;
    route->metric = NETPLAN_METRIC_UNSPEC;
    route->table = 1001;
    route->to = "0.0.0.0/0";
    route->via = "10.0.0.200";
    route->from = NULL;

    assert_true(is_route_present(netdef, route));

    route->table = 1002;
    route->to = "0.0.0.0/0";
    route->via = "10.0.0.200";
    route->from = NULL;

    assert_true(is_route_present(netdef, route));

    route->table = NETPLAN_ROUTE_TABLE_UNSPEC;
    route->to = "192.168.0.0/24";
    route->via = "10.20.30.40";
    route->from = NULL;

    assert_true(is_route_present(netdef, route));

    route->table = 1002;
    route->to = "0.0.0.0/0";
    route->via = "10.0.0.100";
    route->from = NULL;

    assert_false(is_route_present(netdef, route));

    route->table = 1003;
    route->to = "0.0.0.0/0";
    route->via = "10.0.0.200";
    route->from = NULL;

    assert_false(is_route_present(netdef, route));

    route->table = 1001;
    route->to = "default";
    route->via = "10.0.0.200";
    route->from = NULL;

    assert_true(is_route_present(netdef, route));

    route->table = NETPLAN_ROUTE_TABLE_UNSPEC;
    route->family = AF_INET6;
    route->to = "::/0";
    route->via = "abcd::1";
    route->from = NULL;

    assert_true(is_route_present(netdef, route));

    route->table = NETPLAN_ROUTE_TABLE_UNSPEC;
    route->family = AF_INET;
    route->to = "192.168.0.0/24";
    route->via = NULL;
    route->from = NULL;
    route->scope = "link";

    assert_true(is_route_present(netdef, route));

    g_free(route);
    netplan_state_clear(&np_state);
}

void
test_normalize_ip_address(void** state)
{
    assert_string_equal(normalize_ip_address("default", AF_INET), "0.0.0.0/0");
    assert_string_equal(normalize_ip_address("default", AF_INET6), "::/0");
    assert_string_equal(normalize_ip_address("0.0.0.0/0", AF_INET), "0.0.0.0/0");
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
           cmocka_unit_test(test_netplan_netdef_get_output_filename_nm_with_ssid),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_nm_without_ssid),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_networkd),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_buffer_is_too_small),
           cmocka_unit_test(test_netplan_netdef_get_output_filename_invalid_backend),
           cmocka_unit_test(test_util_is_route_present),
           cmocka_unit_test(test_normalize_ip_address),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
