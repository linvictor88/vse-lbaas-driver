#!/usr/bin/python

import httplib2
import json
import base64


class VsmAPI():

    def __init__(self, url, user, password):
        self.authToken = base64.encodestring(user + ':' + password)
        self.url = url

    def _useHeaders(self):
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Basic ' + self.authToken
        }

    def api(self, method, uri, params=None):
        url = self.url + uri
        http = httplib2.Http()
        http.disable_ssl_certificate_validation = True
        if params:
            return http.request(
                url, method, body=json.dumps(params),
                headers=self._useHeaders())
        else:
            return http.request(url, method, headers=self._useHeaders())
