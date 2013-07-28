# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack LLC.
# All Rights Reserved.
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


from quantum.openstack.common import log as logging
from quantum.plugins.services.agent_loadbalancer.drivers.vedge.vmware.vshield.vseapi import VseAPI
from quantum.plugins.services.agent_loadbalancer.drivers.vedge.lbapi import LoadBalancerAPI
from quantum.plugins.services.agent_loadbalancer.drivers.vedge import (
    cfg as hacfg
)

from oslo.config import cfg

LOG = logging.getLogger(__name__)

edgeUri = 'https://10.117.5.245'
edgeId = 'edge-7'
edgeUser = 'admin'
edgePasswd = 'default'


OPTS = [ 
        cfg.StrOpt('pool_vseid',
                    help='this is a vseid of pool'),
        cfg.StrOpt('vip_vseid',
                    help='this is a vseid of vip')
        ]   

class VShieldEdgeLB():

    supported_extension_aliases = ["lbaas"]

    def __init__(self):
        # Hard coded for now
        vseapi = VseAPI(edgeUri, edgeUser, edgePasswd, edgeId)
        self.vselbapi = LoadBalancerAPI(vseapi)
        self.conf = cfg.CONF
        self._max_monitors =  255
        count = 0
        while count < self._max_monitors:
            monitorMap =  "monitorMap_%d" % count
            OPTS.append(cfg.ListOpt(monitorMap))
            count = count + 1
        self.conf.register_opts(OPTS)

    def ini_update(self, ini_path):
        argv = ["--config-file", ini_path]
        self.conf(argv)

    def ini2vseid(self, ini_path):
        pool_vseid = self.conf.pool_vseid
        vip_vseid  = self.conf.vip_vseid 
        return (pool_vseid, vip_vseid)

    def extract_monitorids(self, monitors):
        monitor_ids = []
        for monitor in monitors:
            monitor_ids.append(monitor['id'])
        return monitor_ids

    def extract_vsemonitor_maps(self):
        monitor_maps = {}
        count = 0
        while count < self._max_monitors:
            monitorMap =  "monitorMap_%d" % count
            opt = "self.conf.{}".format(monitorMap)
            monitorMap = eval(opt)
            if monitorMap is not None:
                monitor_id = monitorMap[0]
                monitor_vseid = monitorMap[1]
                monitor_maps[monitor_id] = monitor_vseid
            else:
                return monitor_maps
            count = count + 1
        return monitor_maps

    def ini2monitorvseids(self, monitor_ids, monitor_maps):
        monitor_vseids = {}
        monitor_vseids_delete = {}
        for k,v in monitor_maps.items():
            if k in monitor_ids:
                monitor_vseids[k] = v
            else:
                monitor_vseids_delete[k] = v
        return (monitor_vseids,monitor_vseids_delete) 

#    def ini2monitorvseids2(self, ini_path):
#        monitor_vseids = {}
#        except_opts = ("config_file", "config_dir", "pool_vseid", "vip_vseid")
#        opts = self.conf._opts()
#        print "opts: %s" % opts
#        for index in opts.keys():
#            if index not in except_opts:
#                opt = "self.conf.{}".format(index)
#                index = eval(opt)
#                if index is not None:
#                    monitor_id = index[0]
#                    monitor_vseid = index[1]
#                    monitor_vseids[monitor_id] = monitor_vseid
#        return monitor_vseids

    def create(self, logical_config, ini_path, conf_path):
        monitors = logical_config['healthmonitors']
        members = logical_config['members']
        pool = logical_config['pool']
        vip  = logical_config['vip']
        if monitors is not None:
            #try:
            monitor_vseids,monitors_request = self.vselbapi.create_monitors(monitors)
            #except Exception:
            #    LOG.error(_("monitors create error %s") % monitors)
            #    exit(1)

        #try:
        pool_vseid,pool_request = self.vselbapi.create_pool(pool, members, monitor_vseids)
        if vip is not None:
            vip_vseid,vip_request = self.vselbapi.create_vip(vip, pool_vseid)
        #except Exception:
        #    hacfg.save_ini(ini_path, pool_vseid, None, monitor_vseids) 
        #    self.vselbapi.delete_monitors(ini_path)
        #    self.vselbapi.delete_pool(ini_path)
        #    print "pool or vip create error!"
        #    exit(1)
        hacfg.save_ini(ini_path, pool_vseid, vip_vseid, monitor_vseids)        
        hacfg.save_conf(conf_path, pool_request, vip_request)

    def update(self, logical_config, ini_path, conf_path):
        self.ini_update(ini_path)
        monitors = logical_config['healthmonitors']
        members = logical_config['members']
        pool = logical_config['pool']
        vip  = logical_config['vip']
        pool_vseid,vip_vseid = self.ini2vseid(ini_path) 
        monitor_ids = self.extract_monitorids(monitors)
        old_vsemonitor_maps = self.extract_vsemonitor_maps()
        monitor_vseids_update,monitor_vseids_delete =  self.ini2monitorvseids(monitor_ids, old_vsemonitor_maps)
        #try:
        if monitors is not None:
            monitor_vseids,monitors_request = self.vselbapi.update_monitors(monitors, old_vsemonitor_maps,
                                                                            monitor_ids, monitor_vseids_update,
                                                                            monitor_vseids_delete, pool_vseid)

        pool_vseid,pool_request = self.vselbapi.update_pool(pool, pool_vseid, members, monitor_vseids)
        if vip is not None:
            vip_vseid,vip_request = self.vselbapi.update_vip(vip, pool_vseid, vip_vseid)
        #except Exception:
        #    print "pool or vip update error!"
        #    exit(1)
        hacfg.save_ini(ini_path, pool_vseid, vip_vseid, monitor_vseids)        
        hacfg.save_conf(conf_path, pool_request, vip_request)

    def destroy(self, pool_id, ini_path, conf_path):
        self.ini_update(ini_path)
        pool_vseid,vip_vseid = self.ini2vseid(ini_path) 
        monitor_vseids = self.extract_vsemonitor_maps()
#        monitor_vseids =  self.ini2monitorvseids2(ini_path)
        if vip_vseid is not None:
            self.vselbapi.delete_vip(vip_vseid)
        self.vselbapi.delete_pool(pool_vseid, monitor_vseids)
        if monitor_vseids is not None:
            self.vselbapi.delete_monitors(monitor_vseids, pool_vseid)

    def get_stats(pool_id, ini_path, conf_path):
#        self.vselbapi.get_stats()
        self.vselbapi.get_config()
        
                 
