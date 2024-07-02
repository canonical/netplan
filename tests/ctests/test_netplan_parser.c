#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <sys/stat.h>
#include <sys/mman.h>

#include <cmocka.h>
#include <yaml.h>

#include "netplan.h"
#include "parse.h"
#include "util.h"
#include "util-internal.h"

#include "test_utils.h"

void
test_netplan_parser_new_parser(__unused void** state)
{
    NetplanParser* npp = netplan_parser_new();
    assert_non_null(npp);
    netplan_parser_clear(&npp);
}

void
test_netplan_parser_load_yaml(__unused void** state)
{
    const char* filename = FIXTURESDIR "/bridge.yaml";
    GError *error = NULL;
    NetplanParser* npp = netplan_parser_new();

    gboolean res = netplan_parser_load_yaml(npp, filename, &error);

    assert_true(res);

    netplan_parser_clear(&npp);
}

void
test_netplan_parser_load_yaml_from_fd(__unused void** state)
{
    const char* filename = FIXTURESDIR "/bridge.yaml";
    FILE* f = fopen(filename, "r");
    GError *error = NULL;

    NetplanParser* npp = netplan_parser_new();
    gboolean res = netplan_parser_load_yaml_from_fd(npp, fileno(f), &error);
    assert_true(res);

    netplan_parser_clear(&npp);
    netplan_error_clear(&error);
    fclose(f);
}

void
test_netplan_parser_load_nullable_fields(__unused void** state)
{
    const char* filename = FIXTURESDIR "/nullable.yaml";
    FILE* f = fopen(filename, "r");
    GError *error = NULL;

    NetplanParser* npp = netplan_parser_new();
    assert_null(npp->null_fields);
    gboolean res = netplan_parser_load_nullable_fields(npp, fileno(f), &error);
    assert_true(res);
    assert_non_null(npp->null_fields);
    assert_true(g_hash_table_contains(npp->null_fields, "\tnetwork\tethernets\teth0\tdhcp4"));

    netplan_parser_clear(&npp);
    netplan_error_clear(&error);
    fclose(f);
}

void
test_netplan_parser_load_nullable_overrides(__unused void** state)
{
    const char* filename = FIXTURESDIR "/optional.yaml";
    FILE* f = fopen(filename, "r");
    GError *error = NULL;

    NetplanParser* npp = netplan_parser_new();
    assert_null(npp->null_overrides);
    gboolean res = netplan_parser_load_nullable_overrides(npp, fileno(f), "hint.yaml", &error);
    assert_true(res);
    assert_non_null(npp->null_overrides);
    assert_string_equal(g_hash_table_lookup(npp->null_overrides, "\tnetwork\trenderer"), "hint.yaml");
    assert_string_equal(g_hash_table_lookup(npp->null_overrides, "\tnetwork\tethernets\teth0"), "hint.yaml");

    netplan_parser_clear(&npp);
    netplan_error_clear(&error);
    fclose(f);
}

void
test_netplan_parser_interface_has_bridge_netdef(__unused void** state)
{

    NetplanState *np_state = load_fixture_to_netplan_state("bridge.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "enp3s0");

    NetplanNetDefinition* bridge = netplan_netdef_get_bridge_link(interface);

    assert_non_null(interface);
    assert_non_null(bridge);

    assert_ptr_equal(interface->bridge_link, bridge);

    netplan_state_clear(&np_state);

}

void
test_netplan_parser_interface_has_bond_netdef(__unused void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("bond.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eth0");

    NetplanNetDefinition* bond = netplan_netdef_get_bond_link(interface);

    assert_non_null(interface);
    assert_non_null(bond);

    assert_ptr_equal(interface->bond_link, bond);

    netplan_state_clear(&np_state);

}

void
test_netplan_parser_interface_has_peer_netdef(__unused void** state)
{

    NetplanState* np_state = load_fixture_to_netplan_state("ovs.yaml");

    NetplanNetDefinition* patch0 = netplan_state_get_netdef(np_state, "patch0-1");

    NetplanNetDefinition* patch1 = netplan_netdef_get_peer_link(patch0);
    patch0 = netplan_netdef_get_peer_link(patch1);

    assert_non_null(patch0);
    assert_non_null(patch1);

    assert_ptr_equal(patch0->peer_link, patch1);
    assert_ptr_equal(patch1->peer_link, patch0);

    netplan_state_clear(&np_state);
}

void
test_netplan_parser_sriov_embedded_switch(__unused void** state)
{

    char embedded_switch[16];

    NetplanState* np_state = load_fixture_to_netplan_state("sriov.yaml");

    NetplanNetDefinition* interface = netplan_state_get_netdef(np_state, "eno1");

    _netplan_netdef_get_embedded_switch_mode(interface, embedded_switch, sizeof(embedded_switch) - 1);

    assert_string_equal(embedded_switch, "switchdev");

    netplan_state_clear(&np_state);
}

/* process_document() shouldn't return a missing interface as error if a previous error happened
 * LP#2000324
 */
void
test_netplan_parser_process_document_proper_error(__unused void** state)
{

    NetplanParser *npp = netplan_parser_new();
    yaml_document_t *doc = &npp->doc;
    GError *error = NULL;
    const char* filepath = FIXTURESDIR "/invalid_route.yaml";

    load_yaml(filepath, doc, NULL);

    char* source = g_strdup(filepath);
    npp->sources = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    g_hash_table_add(npp->sources, source);
    npp->ids_in_file = g_hash_table_new(g_str_hash, NULL);
    npp->current.filepath = g_strdup(filepath);
    process_document(npp, &error);

    yaml_document_delete(doc);
    g_free((void *)npp->current.filepath);
    npp->current.filepath = NULL;
    g_hash_table_destroy(npp->ids_in_file);
    npp->ids_in_file = NULL;
    netplan_parser_clear(&npp);

    /* In this instance the interface IS defined and the actual problem is the malformed IP address */
    gboolean found = strstr(error->message, "invalid IP family '-1'") != NULL;
    netplan_error_clear(&error);
    assert_true(found);
}

void
test_netplan_parser_process_document_missing_interface_error(__unused void** state)
{

    NetplanParser *npp = netplan_parser_new();
    yaml_document_t *doc = &npp->doc;
    GError *error = NULL;
    const char* filepath = FIXTURESDIR "/missing_interface.yaml";

    load_yaml(filepath, doc, NULL);

    char* source = g_strdup(filepath);
    npp->sources = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    g_hash_table_add(npp->sources, source);
    npp->ids_in_file = g_hash_table_new(g_str_hash, NULL);
    npp->current.filepath = g_strdup(filepath);
    process_document(npp, &error);

    yaml_document_delete(doc);
    g_free((void *)npp->current.filepath);
    npp->current.filepath = NULL;
    g_hash_table_destroy(npp->ids_in_file);
    npp->ids_in_file = NULL;
    netplan_parser_clear(&npp);

    gboolean found = strstr(error->message, "br0: interface 'ens3' is not defined") != NULL;
    netplan_error_clear(&error);
    assert_true(found);
}

void
test_nm_device_backend_is_nm_by_default(__unused void** state)
{
    const char* yaml =
        "network:\n"
        "  version: 2\n"
        "  nm-devices:\n"
        "    device0:\n"
        "      networkmanager:\n"
        "        uuid: db5f0f67-1f4c-4d59-8ab8-3d278389cf87\n"
        "        name: connection-123\n"
        "        passthrough:\n"
        "          connection.type: vpn\n";

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    netdef = netplan_state_iterator_next(&iter);

    assert_true(netdef->backend == NETPLAN_BACKEND_NM);

    netplan_state_clear(&np_state);
}

void
test_parser_flags(__unused void** state)
{
    NetplanParser* npp = netplan_parser_new();
    GError *error = NULL;
    gboolean ret = netplan_parser_set_flags(npp, NETPLAN_PARSER_IGNORE_ERRORS, &error);

    assert_true(ret);
    assert_null(error);
    assert_int_equal(netplan_parser_get_flags(npp), NETPLAN_PARSER_IGNORE_ERRORS);

    netplan_parser_clear(&npp);
}

void
test_parser_flags_bad_flags(__unused void** state)
{
    NetplanParser* npp = netplan_parser_new();
    GError *error = NULL;
    // Flag 1 << 29 doesn't exist (at least for now)
    gboolean ret = netplan_parser_set_flags(npp, 1 << 29, &error);

    assert_false(ret);
    assert_string_equal(error->message, "Invalid flag set");
    assert_int_equal(error->domain, NETPLAN_PARSER_ERROR);
    assert_int_equal(error->code, NETPLAN_ERROR_INVALID_FLAG);
    netplan_error_clear(&error);
    netplan_parser_clear(&npp);
}

void
test_parser_flags_ignore_errors(__unused void** state)
{
    const char* yaml1 =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth0: {}\n";

    const char* yaml2 = ":";

    const char* yaml3 =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth1:\n"
        "      dhcp4: yesplease\n"
        "    eth2: {}\n";

    const char* yaml4 =
        "network:\n"
        "  version: 2\n"
        "  ethernets:\n"
        "    eth3: {}\n";

    GError *error = NULL;
    char template[] = "/tmp/netplan-XXXXXX";
    char* tempdir = mkdtemp(template);
    g_autofree gchar* etcpath = g_strdup_printf("%s/etc", tempdir);
    g_autofree gchar* fullpath = g_strdup_printf("%s/etc/netplan/", tempdir);
    g_autofree gchar* file1 = g_strdup_printf("%s/etc/netplan/file1.yaml", tempdir);
    g_autofree gchar* file2 = g_strdup_printf("%s/etc/netplan/file2.yaml", tempdir);
    g_autofree gchar* file3 = g_strdup_printf("%s/etc/netplan/file3.yaml", tempdir);
    g_autofree gchar* file4 = g_strdup_printf("%s/etc/netplan/file4.yaml", tempdir);
    g_mkdir_with_parents(fullpath, 0770);
    mode_t old_umask = umask(0077);
    FILE* f1 = fopen(file1, "w");
    FILE* f2 = fopen(file2, "w");
    FILE* f3 = fopen(file3, "w");
    FILE* f4 = fopen(file4, "w");

    fwrite(yaml1, strlen(yaml1), 1, f1);
    fclose(f1);
    fwrite(yaml2, strlen(yaml2), 1, f2);
    fclose(f2);
    fwrite(yaml3, strlen(yaml3), 1, f3);
    fclose(f3);
    fwrite(yaml4, strlen(yaml4), 1, f4);
    fclose(f4);

    umask(old_umask);

    NetplanParser* npp = netplan_parser_new();
    netplan_parser_set_flags(npp, NETPLAN_PARSER_IGNORE_ERRORS, &error);
    gboolean ret = netplan_parser_load_yaml_hierarchy(npp, tempdir, &error);

    // Despite the errors in the YAML it should report success
    assert_true(ret);
    assert_null(error);

    assert_int_equal(netplan_parser_get_flags(npp), NETPLAN_PARSER_IGNORE_ERRORS);

    // The number of errors should be two
    assert_int_equal(netplan_parser_get_error_count(npp), 2);

    NetplanState* np_state = netplan_state_new();
    netplan_state_import_parser_results(np_state, npp, &error);
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    netplan_state_iterator_init(np_state, &iter);

    // Check if all the good netdefs are present in the state
    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "eth0");

    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "eth1");
    assert_false(netplan_netdef_get_dhcp4(netdef));

    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "eth2");

    netdef = netplan_state_iterator_next(&iter);
    assert_string_equal(netdef->id, "eth3");

    netplan_parser_clear(&npp);
    netplan_state_clear(&np_state);

    unlink(file1);
    unlink(file2);
    unlink(file3);
    unlink(file4);
    rmdir(fullpath);
    rmdir(etcpath);
    rmdir(tempdir);
}

void
test_parse_utf8_characters(__unused void** state)
{
    NetplanState *np_state = NULL;
    int fd;
    int size;
    int res;

    char* yaml =
        "network:\n"
        "  version: 2\n"
        "  wifis:\n"
        "    wlan0:\n"
        "      access-points:\n"
        "        \"áéíóúÁÉÍÓÚ\":\n"
        "           password: \"áéíóúÁÉÍÓÚ\"\n";

    char* expected =
        "network:\n"
        "  version: 2\n"
        "  wifis:\n"
        "    wlan0:\n"
        "      access-points:\n"
        "        \"áéíóúÁÉÍÓÚ\":\n"
        "          auth:\n"
        "            key-management: \"psk\"\n"
        "            password: \"áéíóúÁÉÍÓÚ\"\n";

    np_state = load_string_to_netplan_state(yaml);

    fd = memfd_create("netplan-tests", 0);

    netplan_state_dump_yaml(np_state, fd, NULL);

    size = lseek(fd, 0, SEEK_CUR) + 1;
    yaml = malloc(size);
    memset(yaml, 0, size);
    lseek(fd, 0, SEEK_SET);
    res = read(fd, yaml, size - 1);
    assert_true(res > 0);

    assert_string_equal(yaml, expected);

    netplan_state_clear(&np_state);
    close(fd);
    free(yaml);
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
           cmocka_unit_test(test_netplan_parser_new_parser),
           cmocka_unit_test(test_netplan_parser_load_yaml),
           cmocka_unit_test(test_netplan_parser_load_yaml_from_fd),
           cmocka_unit_test(test_netplan_parser_load_nullable_fields),
           cmocka_unit_test(test_netplan_parser_load_nullable_overrides),
           cmocka_unit_test(test_netplan_parser_interface_has_bridge_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_bond_netdef),
           cmocka_unit_test(test_netplan_parser_interface_has_peer_netdef),
           cmocka_unit_test(test_netplan_parser_sriov_embedded_switch),
           cmocka_unit_test(test_netplan_parser_process_document_proper_error),
           cmocka_unit_test(test_netplan_parser_process_document_missing_interface_error),
           cmocka_unit_test(test_nm_device_backend_is_nm_by_default),
           cmocka_unit_test(test_parser_flags),
           cmocka_unit_test(test_parser_flags_bad_flags),
           cmocka_unit_test(test_parser_flags_ignore_errors),
           cmocka_unit_test(test_parse_utf8_characters),
       };

       return cmocka_run_group_tests(tests, setup, tear_down);

}
