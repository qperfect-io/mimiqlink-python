"""The code defines a Python class called MimiqConnection which allows a user to authenticate with a remote server,
upload and download files to and from the server, and retrieve execution details for a given execution request ID.
The class depends on the requests and mimetypes modules, which must be imported in the calling script."""
import requests 
import threading
import os
import http.server
import socketserver
import urllib.parse
import os.path
import mimetypes
import threading
import webbrowser
import time

class MimiqConnection:
    def __init__(self, url,timeout=1):
        self.url = url
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.timeout=timeout
        self.refresher_task = None
        self.refresher_interval = 2
    #Initializes a MimiqConnection object with a given URL and timeout value.
     # url is the URL of the remote server, and timeout is the number of seconds 
      #to wait for a response before timing out.
    def authenticate(self, email, password):
        endpoint = "/api/sign-in"
        data = {
            "email": email,
            "password": password
        }
        response = requests.post(self.url + endpoint, json=data, timeout=self.timeout)
        tokens = response.json()
        self.access_token = tokens["token"]
        self.refresh_token = tokens["refreshToken"]
        if response.status_code == 200:
            print("Authentication successful.")
            self.start_refresher()
        else:
            print("Authentication failed.")

#Authenticates with the remote server using a given email and password. If successful
# this method sets the access_token and refresh_token properties of the MimiqConnection object,
# and starts a token refresher thread. If unsuccessful, an error message is printed.
    def start_refresher(self):

        self.refresher_task = threading.Timer(self.refresher_interval, self.refresh)
        self.refresher_task.start()
    #Starts a token refresher thread
    def stop_refresher(self):
        if self.refresher_task is not None:
            self.refresher_task.cancel()
            self.refresher_task = None
    
#Stops the token refresher thread.
    def refresh(self):
        endpoint = "/api/access-token"
        data = {
            "refreshToken": self.refresh_token
        }
        response = requests.post(self.url + endpoint, json=data, timeout=self.timeout)
        tokens = response.json()
        self.access_token = tokens["token"]
        self.refresh_token = tokens["refreshToken"]
        if response.status_code == 200:
            #print("Access token refreshed.")
            self.start_refresher()
        else:
            print("Access token refresh failed.")

#Refreshes the access token using the refresh token.


    def request(self, name,label,uploads):
        endpoint = "/api/request"
        files = [("name", (None, name)), ("label", (None, label))]
        for file in uploads:
            with open(file, "rb") as f:
                files.append(("uploads", (os.path.basename(file), f.read())))
                
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }
        response = requests.post(self.url +endpoint, files=files, headers=headers)
        
        if response.status_code == 200:
            print("Files uploaded successfully.")
        else:
            print(response)

#Uploads files to the remote server. name is the name of the execution request, label is a label for the request, 
#and uploads is a list of file paths to upload. If successful, 
#a success message is printed. If unsuccessful, an error message is printed.

    def fileserver(req):
        requested_file = "/index.html" if req.path == "/" else req.path
        requested_file = urllib.parse.unquote(requested_file)

    
        if not requested_file:
            return http.server.HTTPStatus.FORBIDDEN

        file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "public", requested_file[1:]))

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = ""

        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                file_content = f.read()
                return http.server.BaseHTTPRequestHandler.build_response(
                    status=200, headers={"Content-Type": mime_type}, data=file_content
                )

        return http.server.HTTPStatus.NOT_FOUND
#A static method which serves files from a local directory. Used for testing.

    def connect(self):
        executionRequestId = "640f112300514323466c0e35"
        endpoint = f"/api/request/{executionRequestId}"

        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        response = requests.get(self.url + endpoint, headers=headers)
        if response.status_code == 200:
            execution_data = response.json()
            print(f"Execution details retrieved for ID {executionRequestId}: {execution_data}")
        else:
            print(f"Failed to retrieve execution details for ID {executionRequestId}: {response}")

 #Retrieves execution details for a given execution request ID. If successful, 
 # a success message is printed along with the execution details. 
 # If unsuccessful, an error message is printed.

    def download_file(self, executionRequestId, index, uploads):
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

        endpoint = f"/api/files/{executionRequestId}/{index}?source={uploads}"

        # add a delay before the first download attempt
        time.sleep(5)
        max_retries = 5
        for retry in range(max_retries):
            response = requests.get(self.url + endpoint, headers=headers)

            if response.status_code == 200:
                print(response.headers)
                file_name="1.txt"
                with open("1.txt", "wb") as f:
                    f.write(response.content)
                print(f"Downloaded {file_name} successfully.")
                break
            elif response.status_code == 202:
                print(f"Server is still processing the request. Retrying in {response}")
                time.sleep(10*(retry+1))
            else:
                print(f"Failed to download {self.url +endpoint}. Status code: {response.status_code}")
                break


#Downloads a file from the remote server. executionRequestId is the ID of the execution request to download from,
#  index is the index of the file to download, and uploads is the upload path for the file. If successful, 
# the file is downloaded and a success message is printed. If unsuccessful, an error message is printed. The method includes a retry mechanism 
# which retries the download several times if the server is still processing the request.