import mimetypes
import requests
from http.server import BaseHTTPRequestHandler

class AuthenticationHandler(BaseHTTPRequestHandler):
    def __init__(self, authenticate_function, *args, **kwargs):
        self.authenticate_function = authenticate_function
        # BaseHTTPRequestHandler calls do_GET **inside** __init__ !!!
        # So we have to call super().__init__ after setting attributes.
        super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            if self.path == '/':
                self.path = '/index.html'
            filepath = os.getcwd() + '/public' + self.path

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
                data = json.loads(body)
                email = data['email']
                password = data['password']
                self.authenticate_function(email, password)
                self.send_response(200)
            except:
                self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(bytes('{"success": true}', 'utf-8'))
        else:
            self.send_error(404)
