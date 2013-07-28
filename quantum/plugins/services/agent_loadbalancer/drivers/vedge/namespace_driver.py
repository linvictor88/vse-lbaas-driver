# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 New Dream Network, LLC (DreamHost)
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Mark McClain, DreamHost
import os
import shutil
import socket

import netaddr

from quantum.agent.linux import ip_lib
from quantum.agent.linux import utils
from quantum.common import exceptions
from quantum.openstack.common import log as logging
##2
from quantum.plugins.services.agent_loadbalancer.drivers.vedge import (
    cfg as hacfg
)
###2
from quantum.plugins.services.agent_loadbalancer.drivers.vedge.vselb import VShieldEdgeLB

LOG = logging.getLogger(__name__)
NS_PREFIX = 'qlbaas-'


class VShieldEdgeDriver(object):
    def __init__(self, root_helper, state_path, vif_driver, vip_plug_callback):
        self.root_helper = root_helper
        self.state_path = state_path
        self.vif_driver = vif_driver
        self.vip_plug_callback = vip_plug_callback
        self.pool_to_port_id = {}
        self.vselb = VShieldEdgeLB()

    def create(self, logical_config):
        pool_id = logical_config['pool']['id']
        namespace = get_ns_name(pool_id)

        self._plug(namespace, logical_config['vip']['port'])
        conf_path = self._get_state_file_path(pool_id, 'conf')
        ini_path = self._get_state_file_path(pool_id, 'ini')
        self.vselb.create(logical_config, ini_path, conf_path)
        self.pool_to_port_id[pool_id] = logical_config['vip']['port']['id']

    def update(self, logical_config):
        pool_id = logical_config['pool']['id']
        conf_path = self._get_state_file_path(pool_id, 'conf')
        ini_path = self._get_state_file_path(pool_id, 'ini')
        self.vselb.update(logical_config, ini_path, conf_path)
        self.pool_to_port_id[pool_id] = logical_config['vip']['port']['id']

    def destroy(self, pool_id):
        namespace = get_ns_name(pool_id)
        ns = ip_lib.IPWrapper(self.root_helper, namespace)
        conf_path = self._get_state_file_path(pool_id, 'conf')
        ini_path = self._get_state_file_path(pool_id, 'ini')
        self.vselb.destroy(pool_id, ini_path, conf_path)

        # unplug the ports
        if pool_id in self.pool_to_port_id:
            self._unplug(namespace, self.pool_to_port_id[pool_id])

        # remove the configuration directory
        conf_dir = os.path.dirname(self._get_state_file_path(pool_id, ''))
        if os.path.isdir(conf_dir):
            shutil.rmtree(conf_dir)
        ns.garbage_collect_namespace()

    def exists(self, pool_id):
        namespace = get_ns_name(pool_id)
        root_ns = ip_lib.IPWrapper(self.root_helper)
        conf_path = self._get_state_file_path(pool_id, 'conf')
        ini_path = self._get_state_file_path(pool_id, 'ini')

        if root_ns.netns.exists(namespace) and os.path.exists(ini_path):
            return True
#            try:
#                self.vselb.update(logical_config, ini_path, conf_path)
#                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
#                s.connect(socket_path)
#                return True
#            except socket.error:
#                pass
        return False

    def get_stats(self, pool_id):
        conf_path = self._get_state_file_path(pool_id, 'conf')
        ini_path = self._get_state_file_path(pool_id, 'ini')
        if os.path.exists(ini_path):
            try:
                return self.vselb.get_stats(pool_id, ini_path, conf_path) 
            except Exception:
                pass
        else:
            LOG.warn(_('Stats socket not found for pool %s') % pool_id)
            return {}

    def remove_orphans(self, known_pool_ids):
        raise NotImplementedError()

    def _get_state_file_path(self, pool_id, kind, ensure_state_dir=True):
        """Returns the file name for a given kind of config file."""
        confs_dir = os.path.abspath(os.path.normpath(self.state_path))
        conf_dir = os.path.join(confs_dir, pool_id)
        if ensure_state_dir:
            if not os.path.isdir(conf_dir):
                os.makedirs(conf_dir, 0755)
        return os.path.join(conf_dir, kind)

    def _plug(self, namespace, port, reuse_existing=True):
        self.vip_plug_callback('plug', port)
        interface_name = self.vif_driver.get_device_name(Wrap(port))

        if ip_lib.device_exists(interface_name, self.root_helper, namespace):
            if not reuse_existing:
                raise exceptions.PreexistingDeviceFailure(
                    dev_name=interface_name
                )
        else:
            self.vif_driver.plug(
                port['network_id'],
                port['id'],
                interface_name,
                port['mac_address'],
                namespace=namespace
            )

        cidrs = [
            '%s/%s' % (ip['ip_address'],
                       netaddr.IPNetwork(ip['subnet']['cidr']).prefixlen)
            for ip in port['fixed_ips']
        ]
        self.vif_driver.init_l3(interface_name, cidrs, namespace=namespace)

        gw_ip = port['fixed_ips'][0]['subnet'].get('gateway_ip')
        if gw_ip:
            cmd = ['route', 'add', 'default', 'gw', gw_ip]
            ip_wrapper = ip_lib.IPWrapper(self.root_helper,
                                          namespace=namespace)
            ip_wrapper.netns.execute(cmd, check_exit_code=False)

    def _unplug(self, namespace, port_id):
        port_stub = {'id': port_id}
        self.vip_plug_callback('unplug', port_stub)
        interface_name = self.vif_driver.get_device_name(Wrap(port_stub))
        self.vif_driver.unplug(interface_name, namespace=namespace)


# NOTE (markmcclain) For compliance with interface.py which expects objects
class Wrap(object):
    """A light attribute wrapper for compatibility with the interface lib."""
    def __init__(self, d):
        self.__dict__.update(d)

    def __getitem__(self, key):
        return self.__dict__[key]


def get_ns_name(namespace_id):
    return NS_PREFIX + namespace_id

