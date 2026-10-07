#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <string.h>
#include <sys/stat.h>
#include <linux/limits.h>

#include <cmocka.h>

#include "netplan.h"
#include "util-internal.h"
#include "nm.h"

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

/* A WiFi SSID whose percent-encoded form would make the .nmconnection
 * basename exceed NAME_MAX (255) must fall back to a SHA-256 digest.
 *
 * NM stores non-ASCII SSIDs as semicolon-delimited decimal bytes, e.g.
 * the emoji U+1F600 (😀, UTF-8: F0 9F 98 80) becomes "240;159;152;128;".
 * g_uri_escape_string() encodes each ';' as '%3B' (3 chars), so 20 such
 * emojis → 480-char encoded SSID → 507-byte candidate basename > NAME_MAX.
 */
void
test_write_wifi_long_ssid_uses_hash(__unused void** state)
{
    /* 20× U+1F600 (😀) in NM decimal-byte format */
    const char ssid[] =
        "240;159;152;128;240;159;152;128;240;159;152;128;240;159;152;128;"
        "240;159;152;128;240;159;152;128;240;159;152;128;240;159;152;128;"
        "240;159;152;128;240;159;152;128;240;159;152;128;240;159;152;128;"
        "240;159;152;128;240;159;152;128;240;159;152;128;240;159;152;128;"
        "240;159;152;128;240;159;152;128;240;159;152;128;240;159;152;128;";

    g_autofree char* yaml = g_strdup_printf(
        "network:\n"
        "  version: 2\n"
        "  renderer: NetworkManager\n"
        "  wifis:\n"
        "    wlan0:\n"
        "      dhcp4: true\n"
        "      access-points:\n"
        "        \"%s\":\n"
        "          password: \"s0s3kr1t\"\n",
        ssid);

    NetplanState* np_state = load_string_to_netplan_state(yaml);
    assert_non_null(np_state);
    assert_true(netplan_state_get_netdefs_size(np_state) > 0);

    NetplanNetDefinition* netdef = netplan_state_get_netdef(np_state, "wlan0");
    assert_non_null(netdef);

    char template[] = "/tmp/netplan_nm_test.XXXXXX";
    char* rootdir = mkdtemp(template);
    assert_non_null(rootdir);

    gboolean has_been_written = FALSE;
    GError* error = NULL;
    assert_true(_netplan_netdef_write_nm(np_state, netdef, rootdir, &has_been_written, &error));
    assert_null(error);
    assert_true(has_been_written);

    /* The output filename must use the SHA-256 digest of the raw SSID */
    g_autofree char* hash = g_compute_checksum_for_string(G_CHECKSUM_SHA256, ssid, -1);
    g_autofree char* expected = g_strdup_printf(
        "%s/run/NetworkManager/system-connections/netplan-wlan0-%s.nmconnection",
        rootdir, hash);

    assert_true(g_file_test(expected, G_FILE_TEST_EXISTS));

    /* Basename must be within NAME_MAX */
    const char* basename = strrchr(expected, '/');
    assert_true(strlen(basename + 1) <= NAME_MAX);

    /* Cleanup */
    const gchar *rm_argv[] = { "/bin/rm", "-rf", rootdir, NULL };
    g_spawn_sync(NULL, (gchar**)rm_argv, NULL, G_SPAWN_DEFAULT,
                 NULL, NULL, NULL, NULL, NULL, NULL);

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
        cmocka_unit_test(test_write_wifi_long_ssid_uses_hash),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
