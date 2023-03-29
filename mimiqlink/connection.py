from functools import partial
from http.server import HTTPServer
import logging
import os
import os.path
import re
import requests 
import socketserver
from time import sleep
import threading
import webbrowser

# import the connection handler
from .handler import AuthenticationHandler


class MimiqConnection:
    def __init__(self, url='http://vps-f8c698f6.vps.ovh.net', timeout=1):
        self.url = url
        self.timeout=timeout

        # refresher related variables
        self.refresher_lock = threading.Lock()
        self.refresher_task = None
        self.refresher_interval = 15 * 60

        # tokens
        self.access_token = None
        self.refresh_token = None


    def connect_user(self, email, password):
        "Authenticate to the remote server with the given credentials (email and password)."
        endpoint = "/api/sign-in"

        # prepare the request
        data = {
            "email": email,
            "password": password
        }

        # ask for access tokens
        response = requests.post(self.url + endpoint, json=data, timeout=self.timeout)

        if response.status_code == 200:
            tokens = response.json()

            # set the access tokens
            with self.refresher_lock:
                self.access_token = tokens["token"]
                self.refresh_token = tokens["refreshToken"]

            # refresher thread, running in the background
            self.start_refresher()

            logging.info("Authentication successful.")

        else:
            reason = response.json()["message"]
            logging.error(f"Authentication failed with status code {response.status_code} and reason: {reason}")

    def _weblogin(self, data):
        "Authenticate to the remote server with the given credentials. But return the response."
        endpoint = "/api/sign-in"

        # ask for access tokens
        print(f"sending request to {self.url} + {endpoint}")
        response = requests.post(self.url + endpoint, json=data, timeout=self.timeout)

        if response.status_code == 200:
            tokens = response.json()

            # set the access tokens
            with self.refresher_lock:
                self.access_token = tokens["token"]
                self.refresh_token = tokens["refreshToken"]

            # refresher thread, running in the background
            self.start_refresher()

            logging.info("Authentication successful.")

        else:
            reason = response.json()["message"]
            logging.error(f"Authentication failed with status code {response.status_code} and reason: {reason}")

        return response

    def connect_token(self, token):
        "Authenticate to the remote server with the given refresh token"

        # set the refresh token
        with self.refresher_lock:
            self.refresh_token = token

        # refresh
        status = self.refresh()

        if status:
            logging.info("Authentication successfull.")
            self.start_refresher()
        else:
            logging.error("Authentication failed.")


    def start_refresher(self):
        "Start a refresher task"
        self.refresher_task = threading.Thread(target=self.refresher)
        self.refresher_task.start()


    def refresher(self):
        "Refresher function. Will refresh the access token with the refresh token every configured interval."
        while True:
            sleep(self.refresher_interval)

            status = self.refresh()

            if not status:
                logging.error("Access token refresh failed. Connection is closed")


    def refresh(self):
        "Refresh the access token using the refresh token."
        endpoint = "/api/access-token"

        # prepare the request
        with self.refresher_lock:
            data = {
                "refreshToken": self.refresh_token
            }

        # ask for a new access token
        response = requests.post(self.url + endpoint, json=data, timeout=self.timeout)

        # check if the response is valid
        if response.status_code != 200:
            return false

        tokens = response.json()

        # write the new tokens
        with self.refresher_lock:
            self.access_token = tokens["token"]
            self.refresh_token = tokens["refreshToken"]

        return true


    def request(self, name, label, uploads):
        "Request an execution to the remote server"

        endpoint = "/api/request"

        data = [("name", (None, name)), ("label", (None, label))]

        for file in uploads:
            if isinstance(file, io.IOBase) and not file.closed:
                data.append(("uploads", (os.path.basename(file.name), f)))
            else: 
                data.append(("uploads", (os.path.basename(file), open(file, "rb"))))
                
        response = requests.post(self.url + endpoint, files=data, headers=self.authorization_headers())
        
        if response.status_code != 200:
            logging.error(f"File upload failed with status code {response.status_code}")
            return None

        return response.json()["executionRequestId"]


    def requestinfo(self, request):
        endpoint = f"/api/request/{request}"
        
        headers = self.authorization_headers(extra_headers={"Content-Type": "application/json"})

        response = requests.get(self.url + endpoint, headers=headers)

        if response.status_code != 200:
            print(f"Failed to retrieve execution details for {request}. Server responded with {response.status_cde}")
            return None

        return response.json()


    def authorization_headers(self, extra_headers = {}):
        # fetch the access token
        with self.refresher_lock:
            token = self.access_token

        # build the headers
        headers = { "Authorization": f"Bearer {token}" }
        headers.update(extra_headers)

        return headers


    def download_file(self, request, index, type, destdir=f"./{request}"):
        endpoint = f"/api/files/{request}/{index}?source={type}"

        response = requests.get(self.url + endpoint, headers=headers)

        if response.status_code != 200:
            logging.error(f"Failed to retrieve {type} files for {request}. Server responded with {response.status_code}")
            return None

        filename = re.findall('filename="(.+)"', response.headers.get('Content-Disposition'))

        # Should never happen, but just in case.
        # If it does, we can't do anything about it here. We need to patch the server
        if not filename:
            logging.error(f"Something went wrong. Server is missing the filename")
            return None

        # at this point we should have a valid filename and a valid directory
        # so we write everything to the file
        with open(os.path.join(destdir, filename), 'wb') as f:
            f.write(response.content)

        return name


    def downloadjobfiles(self, request, **kwargs):
        infos = self.requestinfo(request)
        nf = infos.get("numberOfUploadedFiles", 0)

        # if the directory alreayd exists send a warning, otherwise create it
        try:
            os.mkdir(destdir)
        except FileExistsError:
            logging.warning(f"Directory {destdir} already exists.")

        names = []
        for idx in range(nf):
            name = self.download_file(request, idx, "uploads", **kwargs)
            names.append(name)

        return names


    def downloadresults(self, request, **kwargs):
        infos = self.requestinfo(request)
        nf = infos.get("numberOfResultedFiles", 0)

        # if the directory alreayd exists send a warning, otherwise create it
        try:
            os.mkdir(destdir)
        except FileExistsError:
            logging.warning(f"Directory {destdir} already exists.")

        names = []
        for idx in range(nf):
            name = self.download_file(request, idx, "results", **kwargs)
            names.append(name)

        return names


    def connect(self):
        "Authenticate to the remote services by taking credentials from a locally shown login page"
        handler = partial(AuthenticationHandler, lambda data: self._weblogin(data))
        with HTTPServer(('', 0), handler) as httpd:
            port = httpd.server_port
            print(f"Starting authentication server on port {port} (http://localhost:{port})")
            logging.info(f"Starting authentication server on port {port} (http://localhost:{port})")
            while self.access_token is None:
                httpd.handle_request()

