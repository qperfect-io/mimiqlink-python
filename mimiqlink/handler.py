#
# Copyright © 2022-2023 University of Strasbourg. All Rights Reserved.
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
import json
import mimetypes
import os


class AuthenticationHandler(BaseHTTPRequestHandler):
    def __init__(self, authenticate_function, *args, **kwargs):
        self.authenticate_function = authenticate_function
        # BaseHTTPRequestHandler calls do_GET **inside** __init__ !!!
        # So we have to call super().__init__ after setting attributes.
        super().__init__(*args, **kwargs)

    def do_GET(self):
        # try to serve local files in the /pubic folder
        try:
            if self.path == '/':
                self.path = '/index.html'

            public_dir = os.path.join(os.path.dirname(__file__), 'public')
            filepath = os.path.join(public_dir, self.path.lstrip('/'))

            with open(filepath, 'rb') as file:
                content = file.read()
                mimetype, _ = mimetypes.guess_type(filepath)
                if not mimetype:
                    mimetype = ""
                self.send_response(200)
                self.send_header('Content-type', mimetype)
                self.end_headers()
                self.wfile.write(content)
        except:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/login':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            try:
                # get the remote response from the authentication function and
                # then forward it to the local page in order to show proper
                # error messages.
                data = json.loads(body)
                response = self.authenticate_function(data)
                self.send_response(response.status_code)
                # FIX: should be the same content-type as the response?
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response.content)
            except:
                self.send_response(400)
        else:
            self.send_error(404)
