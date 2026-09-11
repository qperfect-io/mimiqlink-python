#
# Copyright © 2022-2026 University of Strasbourg. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from mimiqlink.utils import getLogger


class OpenIdConnectCallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, expected_state, openid, token_setter, *args, **kwargs):
        self.state = expected_state
        self.openid = openid
        self.token_setter = token_setter
        self._status_code = None
        super().__init__(*args, **kwargs)

    def send_response(self, code, message=None):
        self._status_code = code
        super().send_response(code, message)

    def send_error(self, code, message=None):
        self._status_code = code
        super().send_error(code, message)

    def log_message(self, format, *args):
        # Log only if the status code is not 200
        if self._status_code != 200:
            super().log_message(format, *args)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        if parsed_path.path != "/callback":
            self.send_error(code=404)
        else:
            if 'state' not in query_params or 'code' not in query_params:
                self.send_error(code=400, message="Missing query params")
                return
            if self.state == query_params['state'][0]:
                code = query_params["code"][0]
                port = self.server.server_address[1]
                try:
                    token = self.openid.token(
                        grant_type='authorization_code', code=code,
                        redirect_uri=f"http://localhost:{port}/callback"
                    )
                    self.token_setter(token)
                except Exception as e:
                    getLogger().debug(f"Token exchange failed: {e}")
                    self.server.auth_failed = True
                    self.send_error(code=500, message="Failure to get token from authentication server")
                    return

                self.send_response(code=200)
                self.end_headers()
                self.wfile.write(b"You may now close this window")
            else:
                self.send_response(code=400)
                self.end_headers()
                self.wfile.write(b"Invalid state string")