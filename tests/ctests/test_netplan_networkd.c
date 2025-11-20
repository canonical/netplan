#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "util-internal.h"
#include "networkd.c"
#include "gen-networkd.c"

#include "test_utils.h"

void
test_wait_online_utils(__unused void** state)
{
    char template[] = "/tmp/netplan.XXXXXX";
    const char* rootdir = mkdtemp(template);

    // create mock sysfs
    g_autofree gchar* sys = g_strdup_printf("%s/sys", rootdir);
    g_autofree gchar* sys_class = g_strdup_printf("%s/sys/class", rootdir);
    g_autofree gchar* sys_class_net = g_strdup_printf("%s/sys/class/net", rootdir);
    g_autofree gchar* eth99 = g_strdup_printf("%s/sys/class/net/eth99", rootdir);
    g_autofree gchar* eth99_device = g_strdup_printf("%s/device", eth99);
    g_autofree gchar* driver = g_strdup_printf("%s/device/driver", eth99);
    g_autofree gchar* mac = g_strdup_printf("%s/address", eth99);
    g_mkdir_with_parents(eth99_device, 0700);

    // assert MAC address file
    assert_true(g_file_set_contents(mac, "  aa:bb:cc:dd:ee:ff \r\n\n", -1, NULL));
    g_autofree gchar* mac_value = _netplan_sysfs_get_mac_by_ifname("eth99", rootdir);
    assert_string_equal(mac_value, "aa:bb:cc:dd:ee:ff");

    // assert driver link
    assert_int_equal(symlink("../somewhere/drivers/mock_drv", driver), 0);
    g_autofree gchar* driver_value = _netplan_sysfs_get_driver_by_ifname("eth99", rootdir);
    assert_string_equal(driver_value, "mock_drv");

    // Cleanup
    remove(mac);
    remove(driver);
    rmdir(eth99_device);
    rmdir(eth99);
    rmdir(sys_class_net);
    rmdir(sys_class);
    rmdir(sys);
    rmdir(rootdir);
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
        cmocka_unit_test(test_wait_online_utils),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
