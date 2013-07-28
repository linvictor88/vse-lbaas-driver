#!/usr/bin/python

from quantum.openstack.common import log as logging
import copy
from vmware.vshield.vseapi import VseAPI
from quantum.plugins.services.agent_loadbalancer.drivers.vedge import (
    cfg as hacfg
)
import itertools
import json
import sys
from quantum.plugins.services.agent_loadbalancer import constants

LOG = logging.getLogger(__name__)

BALANCE_MAP = {
    constants.LB_METHOD_ROUND_ROBIN: 'round-robin',
    constants.LB_METHOD_LEAST_CONNECTIONS: 'leastconn',
    constants.LB_METHOD_SOURCE_IP: 'source'
}

PROTOCOL_MAP = {
    constants.PROTOCOL_TCP: 'tcp',
    constants.PROTOCOL_HTTP: 'http',
    constants.PROTOCOL_HTTPS: 'tcp',
}



class LoadBalancerAPI():
    def __init__(self, vse):
        self.vse = vse
#        self.uriprefix = '/api/3.0/edges/{0}/loadbalancer'.format(
        self.uriprefix = '/api/4.0/edges/{0}/loadbalancer'.format(
            vse.get_edgeId())
        self.enabled = False

    def lbaas2vsmPool(self, pool, members):
        vsepool = {
            'name': pool['name'],
            'snatEnable': "true",
            'algorithm': BALANCE_MAP.get(pool['lb_method'],
                                         'round-robin'),
            'member': [],
            'monitorId': []
        }
        for member in members:
            vsepool['member'].append({
                'ipAddress': member['address'],
                'port': member['protocol_port']
            })
        return vsepool

    def lbaas2vsmVS(self, vip, pool_vseid):
        vs = {
            'name': vip['name'],
            'ipAddress': vip['address'],
            'protocol': vip['protocol'],
            'port': vip['protocol_port'],
            'defaultPoolId': pool_vseid
        }
        return vs

    def lbaas2vsmMonitor(self, monitor):
        #print "enter lbaas2vsmMonitor"
        monitor = {
            'type': PROTOCOL_MAP.get(monitor['type'], 'tcp'),
            'interval': monitor['delay'],
            'timeout': monitor['timeout'],
            'maxRetries': monitor['max_retries'],
            #'method': monitor['http_method'],
            #'url': monitor['url'],
            'name': monitor['id'],
        }
        #print "exit lbaas2vsmMonitor"
        return monitor

    def associateMonitors(self, pool, monitor_vseids):
        if len(monitor_vseids) > 1:
            LOG.warn(_("At present, at most one monitor \
                        reference is supported for one Pool"))
        if monitor_vseids is not None:
            for vse_id in monitor_vseids.values():
                pool['monitorId'].append(vse_id)
                return pool
        return pool
    


    def extract_monitor_byid(self, monitors, id):
        LOG.debug(_("Enter extract_monitor_byid,\
                    monitors: %s, id: %s") % 
                    (monitors, id))
        for monitor in monitors:
            if monitor['id'] == id:
                return monitor
        return None

    def extract_monitornames(self, monitors):
        monitor_names = []
        for monitor in monitors:
            monitor_names.append(monitor['name'])
        return monitor_names

    def extract_monitor_byname(self, monitors, name):
        for monitor in monitors:
            if monitor['name'] == name:
                return monitor
        return None

    def create_pool(self, pool, members, monitor_vseids):
        request = self.lbaas2vsmPool(pool, members)
        request = self.associateMonitors(request,monitor_vseids)
        uri = self.uriprefix + '/config/pools'
        header, response = self.vse.vsmconfig('POST', uri, request)
        objuri = header['location']
        pool_vseid = objuri[objuri.rfind("/")+1:]
        
        # currently no way to just do enable, so check if LB is enabled on
        # VSM, if not, do a reconfigure
        if not self.enabled:
            config = self.get_vsm_lb_config()
            if not config['enabled']:
                config['enabled'] = True
                self.__reconfigure(config)
                self.enabled = True
        return (pool_vseid,json.dumps(request))
 
    def update_pool(self, pool, pool_vseid, members, monitor_vseids):
        uri = self.uriprefix + '/config/pools/{0}'.format(pool_vseid)
        request = self.lbaas2vsmPool(pool, members)
        request = self.associateMonitors(request,monitor_vseids)
        response = self.vse.api('PUT', uri, request)
        return (pool_vseid, json.dumps(request))

    def delete_pool(self, pool_vseid, monitor_vseids):
        uri = self.uriprefix + '/config/pools/{0}'.format(pool_vseid)
        response = None
        try:
            header, response = self.vse.vsmconfig('DELETE', uri)
        except Exception:
            pass
        return response

    def delete_pools(self):
        uri = self.uriprefix + '/config/pools'
        response = None
        try:
            header, response = self.vse.vsmconfig('DELETE', uri)
        except Exception:
            pass
        return response

    def create_vip(self, vip, pool_vseid):
        uri = self.uriprefix + '/config/virtualservers'
        request = self.lbaas2vsmVS(vip, pool_vseid)
        header, response = self.vse.vsmconfig('POST', uri, request)
        objuri = header['location']
        vip_vseid = objuri[objuri.rfind("/")+1:]
        return (vip_vseid,json.dumps(request))

    def update_vip(self,vip, pool_vseid, vip_vseid):
        request = self.lbaas2vsmVS(vip, pool_vseid)
        uri = self.uriprefix + '/config/virtualservers/{0}'.format(vip_vseid)
        #request = self.quantum2VSM(vs, self.VirtualServerAttrs)
        response = self.vse.api('PUT', uri, request)
        return (vip_vseid,json.dumps(request))

    def delete_vip(self, vip_vseid):
        uri = self.uriprefix + '/config/virtualservers/{0}'.format(vip_vseid)
        response = self.vse.api('DELETE', uri)
        return response

    def create_monitors(self, monitors):
        LOG.debug(_("Enter create_monitors monitors: %s") % 
                    monitors)
        uri = self.uriprefix + '/config/monitors'
        monitor_vseids = {}
        vsemonitors = self._get_monitors()
        vsemonitors_names = self.extract_monitornames(vsemonitors)
        ### MAP monitor's id with vsemonitor's name
        for monitor in monitors:
            if monitor['id'] not in vsemonitors_names:
                request = self.lbaas2vsmMonitor(monitor)
                header, response = self.vse.vsmconfig('POST', uri, request)
                objuri = header['location']
                monitor_vseid = objuri[objuri.rfind("/")+1:]
                monitor_vseids[monitor['id']] = monitor_vseid
            else:
                monitor_vse = self.extract_monitor_byname(vsemonitors, monitor['id'])
                #print "monitor_vse: %s" % monitor_vse
                monitor_vseid = monitor_vse['monitorId']
                monitor_vseids[monitor['id']] = monitor_vseid
        return (monitor_vseids, None)

    def update_monitors(self, monitors,old_vsemonitor_maps, monitor_ids,
                        monitor_vseids_update, monitor_vseids_delete, pool_vseid):
        LOG.debug(_("Enter update_monitors monitors: %s") % 
                    monitors)
        ##monitors which would call update operation
        for id,monitor_vseid in monitor_vseids_update.items():
            monitor = self.extract_monitor_byid(monitors,id)
            request = self.lbaas2vsmMonitor(monitor)
            uri = self.uriprefix + '/config/monitors/{0}'.format(monitor_vseid)
            response = self.vse.api('PUT', uri, request)

        ##monitors which would call delete operation
            self.delete_monitors(monitor_vseids_delete, pool_vseid)

        ##monitors which would call create operation
        monitors_create = []
        for monitor in monitors:
            if monitor['id'] not in old_vsemonitor_maps.keys():
                monitors_create.append(monitor)
        monitor_vseids_create,request = self.create_monitors(monitors_create)
        monitor_vseids_update.update(monitor_vseids_create)
        
        return (monitor_vseids_update, None)

    def delete_monitors(self, monitor_vseids, pool_vseid):
        pools = self._get_pools()
        monitorids = []
        for pool in pools:
            if pool['poolId'] != pool_vseid:
                for monitorid in pool['monitorId']:
                    monitorids.append(monitorid)
        for id in monitor_vseids.values():
            if id not in monitorids:
                self._delete_monitor(id)
        return None

    def _delete_monitor(self, id):
        ####### need codes to query other pools to decide whether should delete the monitor
        uri = self.uriprefix + '/config/monitors/{0}'.format(id)
        response = self.vse.api('DELETE', uri)
        return response
        

    def get_vsm_lb_config(self):
        uri = self.uriprefix + '/config'
        return self.vse.api('GET', uri)

    def __reconfigure(self, config):
        uri = self.uriprefix + '/config'
        self.vse.vsmconfig('PUT', uri, config)
    
    def _get_monitors(self):
        uri = self.uriprefix + '/config/monitors'
        header, request = self.vse.vsmconfig('GET', uri)
        monitors = request['monitor']
        return monitors

    def _get_pools(self):
        uri = self.uriprefix + '/config/pools'
        header, request = self.vse.vsmconfig('GET', uri)
        monitors = request['pool']
        return monitors

    def get_config(self):
        uri = self.uriprefix + '/config'
        return self.vse.api('GET', uri)


#    def ini2monitorvseids(self, monitor_ids, ini_path):
#        OPTS = [ 
#                cfg.StrOpt('pool_vseid',
#                            default='NULL',                                                                      
#                            help='this is a vseid of pool'),
#                cfg.StrOpt('vip_vseid',
#                            default='NULL',
#                            help='this is a vseid of vip')
#                ]   
#        count = 0
#        while count < len(monitor_ids):
#            monitorMap =  "monitorMap_%d" % count
#            OPTS.append(cfg.ListOpt(monitorMap))
#            count = count + 1
#        self.conf.reset()
##        self.conf.unregister_opts(OPTS)
#        self.conf.register_opts(OPTS)
#        argv = ["--config-file", ini_path]
#        self.conf(argv)
#        monitor_vseids = {}
#        count = 0
#        while count < len(monitor_ids):
#            monitorMap =  "monitorMap_%d" % count
#            opt = "self.conf.{}".format(monitorMap)
#            if eval(opt) is not None:
#                monitor_id = monitorMap[0]
#                monitor_vseid = monitorMap[1]
#                monitor_vseids[monitor_id] = monitor_vseid
#            count = count + 1
#        return monitor_vseids
