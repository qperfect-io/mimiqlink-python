import requests 
import threading
import os


class MimiqConnection:
    def __init__(self, url, timeout=4):
        self.url = url
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.timeout = timeout
        self.refresher_task = None
        self.refresher_interval = 2
    
    def authenticate(self, email, password): 
        endpoint = "/api/sign-in"
        data = {
            "email": email,
            "password": password
        }
        response = self.session.post(self.url + endpoint, json=data, timeout=self.timeout)
        tokens = response.json()
        self.access_token = tokens["token"]
        self.refresh_token = tokens["refreshToken"]
        if response.status_code == 200:
            print("Authentication successful.")
            self.start_refresher()
        else:
            print("Authentication failed.")
    
    def start_refresher(self): 
        self.refresher_task = threading.Timer(self.refresher_interval, self.refresh)
        self.refresher_task.start()
    
    def cancel_refresher(self):
        if self.refresher_task is not None:
            self.refresher_task.cancel()
            self.refresher_task = None
    
    def refresh(self):
        endpoint = "/api/access-token"
        data = {
            "refreshToken": self.refresh_token
        }
        response = self.session.post(self.url + endpoint, json=data, timeout=self.timeout)
        tokens = response.json()
        self.access_token = tokens["token"]
        self.refresh_token = tokens["refreshToken"]
        
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
