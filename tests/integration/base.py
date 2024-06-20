#
# System integration tests of netplan-generate. NM and networkd are
# started on the generated configuration, using emulated ethernets (veth) and
# Wifi (mac80211-hwsim). These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018-2023 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Lukas Märdian <slyon@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import re
import time
import subprocess
import tempfile
import unittest
import shutil
import gi
import glob
import json

# make sure we point to libnetplan properly.
os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})

test_backends = "networkd NetworkManager" if "NETPLAN_TEST_BACKENDS" not in os.environ else os.environ["NETPLAN_TEST_BACKENDS"]

for program in ['wpa_supplicant', 'hostapd', 'dnsmasq']:
    if subprocess.call(['which', program], stdout=subprocess.PIPE) != 0:
        sys.stderr.write('%s is required for this test suite, but not available. Skipping\n' % program)
        sys.exit(0)

nm_uses_dnsmasq = b'dns=dnsmasq' in subprocess.check_output(['NetworkManager', '--print-config'])


def resolved_in_use():
    return os.path.isfile('/run/systemd/resolve/resolv.conf')


class IntegrationTestsBase(unittest.TestCase):
    '''Common functionality for network test cases

    setUp() creates two test ethernet devices (self.dev_e_{ap,client} and
    self.dev_e2_{ap,client}.

    Each test should call self.setup_eth() with the desired configuration.
    '''
    @classmethod
    def setUpClass(klass):
        shutil.rmtree('/etc/netplan', ignore_errors=True)
        os.makedirs('/etc/netplan', exist_ok=True)
        # Try to keep autopkgtest's management network (eth0/ens3) up and
        # configured. It should be running all the time, independently of netplan
        os.makedirs('/etc/systemd/network', exist_ok=True)
        with open('/etc/systemd/network/20-wired.network', 'w') as f:
            f.write('[Match]\nName=eth0 en*\n\n[Network]\nDHCP=yes\nKeepConfiguration=yes')

        # force-reset NM's unmanaged-devices list (using "=" instead of "+=")
        # from /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf,
        # to stop it from trampling over our test & mgmt interfaces.
        # https://pad.lv/1615044
        os.makedirs('/etc/NetworkManager/conf.d', exist_ok=True)
        with open('/etc/NetworkManager/conf.d/90-test-ignore.conf', 'w') as f:
            f.write('[keyfile]\nunmanaged-devices=interface-name:en*,eth0,nptestsrv')
        subprocess.check_call(['netplan', 'apply'])
        subprocess.call(['/lib/systemd/systemd-networkd-wait-online', '--quiet', '--timeout=30'])
        if klass.is_active('NetworkManager.service'):
            subprocess.check_call(['nm-online', '-s'])
            subprocess.check_call(['nmcli', 'general', 'reload'])

    @classmethod
    def tearDownClass(klass):
        pass

    def tearDown(self):
        subprocess.call(['systemctl', 'stop', 'NetworkManager', 'systemd-networkd', 'netplan-wpa-*',
                         'netplan-ovs-*', 'systemd-networkd.socket'])
        # NM has KillMode=process and leaks dhclient processes
        subprocess.call(['systemctl', 'kill', 'NetworkManager'])
        subprocess.call(['systemctl', 'reset-failed', 'NetworkManager', 'systemd-networkd'],
                        stderr=subprocess.DEVNULL)
        shutil.rmtree('/etc/netplan', ignore_errors=True)
        shutil.rmtree('/run/NetworkManager', ignore_errors=True)
        shutil.rmtree('/run/systemd/network', ignore_errors=True)
        for f in glob.glob('/run/systemd/system/netplan-*'):
            os.remove(f)
        for f in glob.glob('/run/systemd/system/**/netplan-*'):
            os.remove(f)
        for f in glob.glob('/run/udev/rules.d/*netplan*'):
            os.remove(f)
        subprocess.call(['systemctl', 'daemon-reload'])
        subprocess.call(['udevadm', 'control', '--reload'])
        subprocess.call(['udevadm', 'trigger', '--attr-match=subsystem=net'])
        subprocess.call(['udevadm', 'settle'])
        try:
            os.remove('/run/systemd/generator/netplan.stamp')
        except FileNotFoundError:
            pass
        # Keep the management network (eth0/ens3 from 20-wired.network) up
        subprocess.check_call(['systemctl', 'restart', 'systemd-networkd'])

    @classmethod
    def create_devices(klass):
        '''Create Access Point and Client devices with veth'''

        if os.path.exists('/sys/class/net/eth42'):
            raise SystemError('eth42 interface already exists')

        klass.dev_e_ap = 'veth42'
        klass.dev_e_client = 'eth42'
        klass.dev_e_ap_ip4 = '192.168.5.1/24'
        klass.dev_e_ap_ip6 = '2600::1/64'

        klass.dev_e2_ap = 'veth43'
        klass.dev_e2_client = 'eth43'
        klass.dev_e2_ap_ip4 = '192.168.6.1/24'
        klass.dev_e2_ap_ip6 = '2601::1/64'

        # don't let NM trample over our test routers
        with open('/etc/NetworkManager/conf.d/99-test-denylist.conf', 'w') as f:
            f.write('[keyfile]\nunmanaged-devices+=%s,%s\n' % (klass.dev_e_ap, klass.dev_e2_ap))
        if klass.is_active('NetworkManager.service'):
            subprocess.check_call(['nm-online', '-s'])
            subprocess.check_call(['nmcli', 'general', 'reload'])

        # create virtual ethernet devs
        subprocess.check_call(['ip', 'link', 'add', 'name', 'eth42', 'type',
                               'veth', 'peer', 'name', 'veth42'])
        subprocess.check_call(['ip', 'link', 'add', 'name', 'eth43', 'type',
                               'veth', 'peer', 'name', 'veth43'])

        # Creation of the veths introduces a race with newer versions of
        # systemd, as it  will change the initial MAC address after the device
        # was created and networkd took control. Give it some time, so we read
        # the correct MAC address
        time.sleep(0.1)
        out = subprocess.check_output(['ip', '-br', 'link', 'show', 'dev', 'eth42'],
                                      text=True)
        klass.dev_e_client_mac = out.split()[2]
        out = subprocess.check_output(['ip', '-br', 'link', 'show', 'dev', 'eth43'],
                                      text=True)
        klass.dev_e2_client_mac = out.split()[2]

    @classmethod
    def shutdown_devices(klass):
        '''Remove test devices'''

        subprocess.check_call(['ip', 'link', 'del', 'dev', klass.dev_e_ap])
        subprocess.check_call(['ip', 'link', 'del', 'dev', klass.dev_e2_ap])
        subprocess.call(['ip', 'link', 'del', 'dev', klass.dev_e_client],
                        stderr=subprocess.PIPE)
        subprocess.call(['ip', 'link', 'del', 'dev', klass.dev_e2_client],
                        stderr=subprocess.PIPE)
        klass.dev_e_ap = None
        klass.dev_e_client = None
        klass.dev_e2_ap = None
        klass.dev_e2_client = None

        subprocess.call(['ip', 'link', 'del', 'dev', 'iface1'],
                        stderr=subprocess.PIPE)
        subprocess.call(['ip', 'link', 'del', 'dev', 'iface2'],
                        stderr=subprocess.PIPE)
        subprocess.call(['ip', 'link', 'del', 'dev', 'mybr'],
                        stderr=subprocess.PIPE)
        subprocess.call(['ip', 'link', 'del', 'dev', 'nptestsrv'],
                        stderr=subprocess.PIPE)
        os.remove('/etc/NetworkManager/conf.d/99-test-denylist.conf')

    def setUp(self):
        '''Create test devices and workdir'''

        self.create_devices()
        self.addCleanup(self.shutdown_devices)
        self.workdir_obj = tempfile.TemporaryDirectory()
        self.workdir = self.workdir_obj.name
        self.config = '/etc/netplan/01-main.yaml'
        os.makedirs('/etc/netplan', exist_ok=True)

        # create static entropy file to avoid draining/blocking on /dev/random
        self.entropy_file = os.path.join(self.workdir, 'entropy')
        with open(self.entropy_file, 'wb') as f:
            f.write(b'012345678901234567890')

    def setup_eth(self, ipv6_mode, start_dnsmasq=True):
        '''Set up simulated ethernet router

        On self.dev_e_ap, run dnsmasq according to ipv6_mode, see
        start_dnsmasq().

        This is torn down automatically at the end of the test.
        '''
        # give our router an IP
        subprocess.check_call(['ip', 'a', 'flush', 'dev', self.dev_e_ap])
        subprocess.check_call(['ip', 'a', 'flush', 'dev', self.dev_e2_ap])
        if ipv6_mode is not None:
            subprocess.check_call(['ip', 'a', 'add', self.dev_e_ap_ip6, 'dev', self.dev_e_ap])
            subprocess.check_call(['ip', 'a', 'add', self.dev_e2_ap_ip6, 'dev', self.dev_e2_ap])
        else:
            subprocess.check_call(['ip', 'a', 'add', self.dev_e_ap_ip4, 'dev', self.dev_e_ap])
            subprocess.check_call(['ip', 'a', 'add', self.dev_e2_ap_ip4, 'dev', self.dev_e2_ap])
        subprocess.check_call(['ip', 'link', 'set', self.dev_e_ap, 'up'])
        subprocess.check_call(['ip', 'link', 'set', self.dev_e2_ap, 'up'])
        if start_dnsmasq:
            self.start_dnsmasq(ipv6_mode, self.dev_e_ap)
            self.start_dnsmasq(ipv6_mode, self.dev_e2_ap)

    #
    # Internal implementation details
    #

    @classmethod
    def poll_text(klass, logpath, string, timeout=50):
        '''Poll log file for a given string with a timeout.

        Timeout is given in deciseconds.
        '''
        log = ''
        while timeout > 0:
            if os.path.exists(logpath):
                break
            timeout -= 1
            time.sleep(0.1)
        assert timeout > 0, 'Timed out waiting for file %s to appear' % logpath

        with open(logpath) as f:
            while timeout > 0:
                line = f.readline()
                if line:
                    log += line
                    if string in line:
                        break
                    continue
                timeout -= 1
                time.sleep(0.1)

        assert timeout > 0, 'Timed out waiting for "%s":\n------------\n%s\n-------\n' % (string, log)

    def start_dnsmasq(self, ipv6_mode, iface):
        '''Start dnsmasq.

        If ipv6_mode is None, IPv4 is set up with DHCP. If it is not None, it
        must be a valid dnsmasq mode, i. e. a combination of "ra-only",
        "slaac", "ra-stateless", and "ra-names". See dnsmasq(8).
        '''
        if ipv6_mode is None:
            if iface == self.dev_e2_ap:
                dhcp_range = '192.168.6.10,192.168.6.200'
            else:
                dhcp_range = '192.168.5.10,192.168.5.200'
        else:
            if iface == self.dev_e2_ap:
                dhcp_range = '2601::10,2601::20'
            else:
                dhcp_range = '2600::10,2600::20'
            if ipv6_mode:
                dhcp_range += ',' + ipv6_mode

        dnsmasq_log = os.path.join(self.workdir, 'dnsmasq-%s.log' % iface)
        lease_file = os.path.join(self.workdir, 'dnsmasq-%s.leases' % iface)

        p = subprocess.Popen(['dnsmasq', '--keep-in-foreground', '--log-queries',
                              '--log-facility=' + dnsmasq_log,
                              '--conf-file=/dev/null',
                              '--dhcp-leasefile=' + lease_file,
                              '--bind-interfaces',
                              '--interface=' + iface,
                              '--except-interface=lo',
                              '--enable-ra',
                              '--dhcp-range=' + dhcp_range])
        self.addCleanup(p.kill)

        if ipv6_mode is not None:
            self.poll_text(dnsmasq_log, 'IPv6 router advertisement enabled')
        else:
            self.poll_text(dnsmasq_log, 'DHCP, IP range')

    def iface_json(self, iface: str) -> dict:
        '''Return iproute2's (detailed) JSON representation'''
        out = subprocess.check_output(['ip', '-j', '-d', 'a', 'show', 'dev', iface],
                                      text=True)
        json_dict = json.loads(out)
        if json_dict:
            return json_dict[0]
        return {}

    def assert_iface(self, iface, expected_ip_a=None, unexpected_ip_a=None):
        '''Assert that client interface has been created'''

        out = subprocess.check_output(['ip', '-d', 'a', 'show', 'dev', iface],
                                      text=True)
        if expected_ip_a:
            for r in expected_ip_a:
                self.assertRegex(out, r, out)
        if unexpected_ip_a:
            for r in unexpected_ip_a:
                self.assertNotRegex(out, r, out)

        return out

    def assert_iface_up(self, iface, expected_ip_a=None, unexpected_ip_a=None):
        '''Assert that client interface is up'''

        out = self.assert_iface(iface, expected_ip_a, unexpected_ip_a)
        if 'bond' not in iface:
            self.assertIn('state UP', out)

    def match_veth_by_non_permanent_mac_quirk(self, netdef_id, mac_match):
        '''
        We cannot match using PermanentMACAddress= on veth type devices. Still,
        we need this capability during testing. So we're applying this quirk to
        install some override config snippet.
        https://github.com/canonical/netplan/pull/278
        '''
        network_dir = '10-netplan-' + netdef_id + '.network.d'
        link_dir = '10-netplan-' + netdef_id + '.link.d'
        for dir in [network_dir, link_dir]:
            path = os.path.join('/run/systemd/network', dir)
            os.makedirs(path, exist_ok=False)  # cleanup is done in tearDown()
            with open(os.path.join(path, 'override.conf'), 'w') as f:
                # clear the PermanentMACAddress= setting and use MACAddress= instead
                f.write('[Match]\nPermanentMACAddress=\nMACAddress={}'.format(mac_match))

    def generate_and_settle(self, wait_interfaces=None, state_dir=None):
        '''Generate config, launch and settle NM and networkd'''

        # regenerate netplan config
        cmd = ['netplan', 'apply']
        if state_dir:
            cmd = cmd + ['--state', state_dir]
        out = ''
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.assertTrue(False, 'netplan apply failed: {}'.format(e.output))

        if 'Run \'systemctl daemon-reload\' to reload units.' in out:
            print('\nWARNING: systemd units changed without reload:', out)
        # start NM so that we can verify that it does not manage anything
        subprocess.call(['nm-online', '-sxq'])  # Wait for NM startup, from 'netplan apply'
        if not self.is_active('NetworkManager.service'):
            subprocess.check_call(['systemctl', 'start', 'NetworkManager.service'])
            subprocess.call(['nm-online', '-sq'])

        # Debugging output
        # out = subprocess.check_output(['NetworkManager', '--print-config'], text=True)
        # print(out, flush=True)
        # out = subprocess.check_output(['nmcli', 'dev'], text=True)
        # print(out, flush=True)

        # Wait for interfaces to be ready:
        ifaces = wait_interfaces if wait_interfaces is not None else [self.dev_e_client, self.dev_e2_client]
        for iface_state in ifaces:
            split = iface_state.split('/', 1)
            iface = split[0]
            state = split[1] if len(split) > 1 else None
            print(iface, end=' ', flush=True)
            if self.backend == 'NetworkManager':
                self.nm_wait_connected(iface, 60)
            else:
                self.networkd_wait_connected(iface, 60)
            # wait for iproute2 state change
            if state:
                self.wait_output(['ip', 'addr', 'show', iface], state, 30)

    def state(self, iface, state):
        '''Tell generate_and_settle() to wait for a specific state'''
        return iface + '/' + state

    def state_up(self, iface):
        '''Tell generate_and_settle() to wait for the interface to be brought UP'''
        return self.state(iface, 'state UP')

    def state_dhcp4(self, iface):
        '''Tell generate_and_settle() to wait for assignment of an IP4 address from DHCP'''
        return self.state(iface, 'inet 192.168.')  # TODO: make this a regex to check for specific DHCP ranges

    def state_dhcp6(self, iface):
        '''Tell generate_and_settle() to wait for assignment of an IP6 address from DHCP'''
        return self.state(iface, 'inet6 260')  # TODO: make this a regex to check for specific DHCP ranges

    def nm_online_full(self, iface, timeout=60):
        '''Wait for NetworkManager connection to be completed (incl. IP4 & DHCP)'''

        gi.require_version('NM', '1.0')
        from gi.repository import NM
        for t in range(timeout):
            c = NM.Client.new(None)
            con = c.get_device_by_iface(iface).get_active_connection()
            if not con:
                self.fail('no active connection for %s by NM' % iface)
            flags = NM.utils_enum_to_str(NM.ActivationStateFlags, con.get_state_flags())
            if "ip4-ready" in flags:
                break
            time.sleep(1)
        else:
            self.fail('timed out waiting for %s to get ready by NM' % iface)

    def wait_output(self, cmd, expected_output, timeout=10):
        for _ in range(timeout):
            try:
                out = subprocess.check_output(cmd, text=True)
            except subprocess.CalledProcessError:
                out = ''
            if expected_output in out:
                break
            sys.stdout.write('.')  # waiting indicator
            sys.stdout.flush()
            time.sleep(1)
        else:
            subprocess.call(cmd)  # print output of the failed command
            self.fail('timed out waiting for "{}" to appear in {}'.format(expected_output, cmd))

    def nm_wait_connected(self, iface, timeout=10):
        subprocess.call(['nm-online', '-sq'])
        self.wait_output(['nmcli', 'dev', 'show', iface], '(connected', timeout)

    def networkd_wait_connected(self, iface, timeout=10):
        # "State: routable (configured)" or "State: degraded (configured)"
        self.wait_output(['networkctl', 'status', iface], '(configured', timeout)

    @classmethod
    def is_active(klass, unit):
        '''Check if given unit is active or activating'''

        p = subprocess.Popen(['systemctl', 'is-active', unit], stdout=subprocess.PIPE)
        out = p.communicate()[0]
        return p.returncode == 0 or out.startswith(b'activating')


class IntegrationTestsWifi(IntegrationTestsBase):
    '''Common functionality for network test cases

    setUp() creates two test wlan devices, one for a simulated access point
    (self.dev_w_ap), the other for a simulated client device
    (self.dev_w_client), and two test ethernet devices (self.dev_e_{ap,client}
    and self.dev_e2_{ap,client}.

    Each test should call self.setup_ap() or self.setup_eth() with the desired
    configuration.
    '''
    @classmethod
    def setUpClass(klass):
        super().setUpClass()
        # ensure we have this so that iw works
        try:
            subprocess.check_call(['modprobe', 'cfg80211'])
            # set regulatory domain "EU", so that we can use 80211.a 5 GHz channels
            out = subprocess.check_output(['iw', 'reg', 'get'], text=True)
            m = re.match(r'^(?:global\n)?country (\S+):', out)
            assert m
            klass.orig_country = m.group(1)
            subprocess.check_call(['iw', 'reg', 'set', 'EU'])
        except Exception:
            raise unittest.SkipTest("cfg80211 (wireless) is unavailable, can't test")

    @classmethod
    def tearDownClass(klass):
        subprocess.check_call(['iw', 'reg', 'set', klass.orig_country])
        super().tearDownClass()

    @classmethod
    def create_devices(klass):
        '''Create Access Point and Client devices with mac80211_hwsim and veth'''
        if os.path.exists('/sys/module/mac80211_hwsim'):
            raise SystemError('mac80211_hwsim module already loaded')
        super().create_devices()
        # create virtual wlan devs
        before_wlan = set([c for c in os.listdir('/sys/class/net') if c.startswith('wlan')])
        subprocess.check_call(['modprobe', 'mac80211_hwsim'])
        # wait 5 seconds for fake devices to appear
        timeout = 50
        while timeout > 0:
            after_wlan = set([c for c in os.listdir('/sys/class/net') if c.startswith('wlan')])
            if len(after_wlan) - len(before_wlan) >= 2:
                break
            timeout -= 1
            time.sleep(0.1)
        else:
            raise SystemError('timed out waiting for fake devices to appear')

        devs = list(after_wlan - before_wlan)
        klass.dev_w_ap = devs[0]
        klass.dev_w_client = devs[1]

        # don't let NM trample over our fake AP
        with open('/etc/NetworkManager/conf.d/99-test-denylist-wifi.conf', 'w') as f:
            f.write('[keyfile]\nunmanaged-devices+=%s\n' % klass.dev_w_ap)

    @classmethod
    def shutdown_devices(klass):
        '''Remove test devices'''
        super().shutdown_devices()
        klass.dev_w_ap = None
        klass.dev_w_client = None
        subprocess.check_call(['rmmod', 'mac80211_hwsim'])
        os.remove('/etc/NetworkManager/conf.d/99-test-denylist-wifi.conf')

    def start_hostapd(self, conf):
        hostapd_conf = os.path.join(self.workdir, 'hostapd.conf')
        with open(hostapd_conf, 'w') as f:
            f.write('interface=%s\ndriver=nl80211\n' % self.dev_w_ap)
            f.write(conf)

        log = os.path.join(self.workdir, 'hostapd.log')
        p = subprocess.Popen(['hostapd', '-e', self.entropy_file, '-f', log, hostapd_conf],
                             stdout=subprocess.PIPE)
        self.addCleanup(p.wait)
        self.addCleanup(p.terminate)
        self.poll_text(log, '' + self.dev_w_ap + ': AP-ENABLED', 500)

    def setup_ap(self, hostapd_conf, ipv6_mode):
        '''Set up simulated access point

        On self.dev_w_ap, run hostapd with given configuration. Setup dnsmasq
        according to ipv6_mode, see start_dnsmasq().

        This is torn down automatically at the end of the test.
        '''
        # give our AP an IP
        subprocess.check_call(['ip', 'a', 'flush', 'dev', self.dev_w_ap])
        if ipv6_mode is not None:
            subprocess.check_call(['ip', 'a', 'add', self.dev_e_ap_ip6, 'dev', self.dev_w_ap])
        else:
            subprocess.check_call(['ip', 'a', 'add', self.dev_e_ap_ip4, 'dev', self.dev_w_ap])
        self.start_hostapd(hostapd_conf)
        self.start_dnsmasq(ipv6_mode, self.dev_w_ap)

    def assert_iface_up(self, iface, expected_ip_a=None, unexpected_ip_a=None):
        '''Assert that client interface is up'''
        super().assert_iface_up(iface, expected_ip_a, unexpected_ip_a)
        if iface == self.dev_w_client:
            out = subprocess.check_output(['iw', 'dev', iface, 'link'],
                                          text=True)
            # self.assertIn('Connected to ' + self.mac_w_ap, out)
            self.assertIn('SSID: fake net', out)
