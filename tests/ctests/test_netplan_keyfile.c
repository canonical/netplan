#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "netplan.h"
#include "parse-nm.h"
#include "parse.h"

#include "error.c"
#include "names.c"
#include "netplan.c"
#include "validation.c"
#include "types.c"
#include "util.c"
#include "parse.c"
#include "parse-nm.c"

#include "test_utils.h"
#include "test_utils_keyfile.h"

void
test_load_keyfile_wifi_wpa_eap(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;
    NetplanWifiAccessPoint* ap = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=mywifi\n"
        "uuid=03c8f2a7-268d-4765-b626-efcc02dd686c\n"
        "type=wifi\n"
        "interface-name=wlp2s0\n"
        "[wifi]\n"
        "mode=infrastructure\n"
        "ssid=mywifi\n"
        "[wifi-security]\n"
        "auth-alg=open\n"
        "key-mgmt=wpa-eap\n"
        "[802-1x]\n"
        "ca-cert=/path/to/cert.crt\n"
        "eap=peap;\n"
        "identity=username\n"
        "password=mypassword\n"
        "phase2-auth=mschapv2\n"
        "[ipv4]\n"
        "method=auto\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);
    ap = g_hash_table_lookup(netdef->access_points, "mywifi");

    assert_string_equal(netdef->id, "NM-03c8f2a7-268d-4765-b626-efcc02dd686c");
    assert_string_equal(ap->ssid, "mywifi");
    assert_string_equal(ap->auth.identity, "username");
    assert_string_equal(ap->auth.ca_certificate, "/path/to/cert.crt");

    netplan_state_clear(&np_state);
}


void
test_load_keyfile_simple_wireguard(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=wg0\n"
        "type=wireguard\n"
        "uuid=19f501f5-9984-429a-a8b5-3f5a89aa460c\n"
        "interface-name=wg0\n"
        "[ipv4]\n"
        "method=auto\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_string_equal(netdef->id, "wg0");
    assert_null(netdef->wireguard_peers);

    netplan_state_clear(&np_state);
}

void
test_load_keyfile_wireguard_with_key_and_peer(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=client-wg0\n"
        "type=wireguard\n"
        "uuid=6352c897-174c-4f61-9623-556eddad05b2\n"
        "interface-name=wg0\n"
        "[wireguard]\n"
        "private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=\n"
        "[wireguard-peer.cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI=]\n"
        "endpoint=1.2.3.4:12345\n"
        "allowed-ips=192.168.0.0/24;\n"
        "[ipv4]\n"
        "method=auto\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_string_equal(netdef->id, "wg0");
    assert_string_equal(netdef->tunnel.private_key, "aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=");

    NetplanWireguardPeer* peer = g_array_index(netdef->wireguard_peers, NetplanWireguardPeer*, 0);
    assert_string_equal(peer->public_key, "cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI=");
    assert_string_equal(peer->endpoint, "1.2.3.4:12345");

    gchar* allowed_ip = g_array_index(peer->allowed_ips, gchar*, 0);
    assert_string_equal(allowed_ip, "192.168.0.0/24");

    netplan_state_clear(&np_state);
}

void
test_load_keyfile_wireguard_with_bad_peer_key(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=client-wg0\n"
        "type=wireguard\n"
        "uuid=6352c897-174c-4f61-9623-556eddad05b2\n"
        "interface-name=wg0\n"
        "[wireguard]\n"
        "private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=\n"
        "[wireguard-peer.this_is_not_a_valid_peer_public_key]\n"
        "endpoint=1.2.3.4:12345\n"
        "allowed-ips=192.168.0.0/24;\n"
        "[ipv4]\n"
        "method=auto\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_null(netdef->wireguard_peers);

    netplan_state_clear(&np_state);
}

void
test_load_keyfile_vxlan(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=vxlan0\n"
        "type=vxlan\n"
        "uuid=6352c897-174c-4f61-9623-556eddad05b2\n"
        "interface-name=vxlan0\n"
        "[vxlan]\n"
        "id=10\n"
        "local=1.2.3.4\n"
        "remote=4.3.2.1\n"
        "[ipv4]\n"
        "method=auto\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_string_equal(netdef->id, "vxlan0");
    assert_int_equal(netdef->vxlan->vni, 10);
    assert_string_equal(netdef->tunnel.local_ip, "1.2.3.4");
    assert_string_equal(netdef->tunnel.remote_ip, "4.3.2.1");

    netplan_state_clear(&np_state);
}

void
test_load_keyfile_multiple_addresses_and_routes(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    const char* keyfile =
        "[connection]\n"
        "id=netplan-enp3s0\n"
        "type=ethernet\n"
        "interface-name=enp3s0\n"
        "uuid=6352c897-174c-4f61-9623-556eddad05b2\n"
        "[ipv4]\n"
        "method=manual\n"
        "address1=10.100.1.38/24\n"
        "address2=10.100.1.39/24\n"
        "route1=0.0.0.0/0,10.100.1.1\n"
        "route1_options=onlink=true,initrwnd=33,initcwnd=44,mtu=1024,table=102\n"
        "route2=192.168.0.0/24,1.2.3.4\n"
        "route2_options=onlink=true,initrwnd=33,initcwnd=44,mtu=1024,table=103\n"
        "[ipv6]\n"
        "method=manual\n"
        "address1=2001:cafe:face::1/64\n"
        "address2=2001:cafe:face::2/64\n"
        "ip6-privacy=0\n"
        "route1=::/0,2001:cafe:face::3/64\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_string_equal(netdef->id, "NM-6352c897-174c-4f61-9623-556eddad05b2");

    netplan_state_clear(&np_state);
}

void
test_load_keyfile_route_options_without_route(__unused void** state)
{
    NetplanState *np_state = NULL;
    NetplanStateIterator iter;
    NetplanNetDefinition* netdef = NULL;

    /* Should this even be allowed? */
    const char* keyfile =
        "[connection]\n"
        "id=netplan-enp3s0\n"
        "type=ethernet\n"
        "interface-name=enp3s0\n"
        "uuid=6352c897-174c-4f61-9623-556eddad05b2\n"
        "[ipv4]\n"
        "method=manual\n"
        "address1=10.100.1.38/24\n"
        "address2=10.100.1.39/24\n"
        "route1_options=onlink=true,initrwnd=33,initcwnd=44,mtu=1024,table=102,src=10.10.10.11\n";

    np_state = load_keyfile_string_to_netplan_state(keyfile);

    netplan_state_iterator_init(np_state, &iter);
    netdef = netplan_state_iterator_next(&iter);

    assert_string_equal(netdef->id, "NM-6352c897-174c-4f61-9623-556eddad05b2");

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
        cmocka_unit_test(test_load_keyfile_wifi_wpa_eap),
        cmocka_unit_test(test_load_keyfile_simple_wireguard),
        cmocka_unit_test(test_load_keyfile_wireguard_with_key_and_peer),
        cmocka_unit_test(test_load_keyfile_wireguard_with_bad_peer_key),
        cmocka_unit_test(test_load_keyfile_vxlan),
        cmocka_unit_test(test_load_keyfile_multiple_addresses_and_routes),
        cmocka_unit_test(test_load_keyfile_route_options_without_route),
    };

    return cmocka_run_group_tests(tests, setup, tear_down);

}
