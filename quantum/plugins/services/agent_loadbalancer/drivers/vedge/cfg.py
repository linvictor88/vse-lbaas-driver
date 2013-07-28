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

import itertools

from oslo.config import cfg

from quantum.agent.linux import utils

def save_ini(ini_path, pool_vseid, vip_vseid, monitor_vseids):
    data = []
    data.extend(_build_ini(pool_vseid, vip_vseid, monitor_vseids))
    utils.replace_file(ini_path, '\n'.join(data))
    

def save_conf(conf_path, pool_request, vip_request):
    data = []
    data.extend(_build_conf(pool_request, vip_request))
    utils.replace_file(conf_path, '\n'.join(data))

def _build_ini(pool_vseid, vip_vseid, monitor_vseids):
    opts = [
        'pool_vseid = %s' % pool_vseid,
        'vip_vseid  = %s' % vip_vseid
    ]
    count = 0
    for k,v in monitor_vseids.items():
        str = "monitorMap_%d = %s, %s" % (count, k, v)
        count = count + 1
        opts.append(str) 
    return itertools.chain(['[DEFAULT]'], (o for o in opts))


def _build_conf(pool_request, vip_request):
    opts = [
        'pool_request \n %s' % pool_request,
        'vip_request \n %s' % vip_request
    ]
    return itertools.chain((o for o in opts))

