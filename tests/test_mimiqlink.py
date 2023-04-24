import unittest
import requests
from unittest.mock import patch, MagicMock
from io import BytesIO
from handler import AuthenticationHandler
from connection import MimiqConnection


class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


class TestMimiqConnection(unittest.TestCase):
    def setUp(self):
        self.mock_response = {"token": "access_token",
                              "refreshToken": "refresh_token"}
        self.connection = MimiqConnection()

    @patch.object(requests.Session, 'post')
    def test_connectUser(self, mock_post):
        mock_post.return_value = MockResponse(self.mock_response, 200)
        self.connection.connectUser("testuser@prova.io", "prova")
        self.assertEqual(self.connection.access_token, "access_token")
        self.assertEqual(self.connection.refresh_token, "refresh_token")

    @patch.object(requests.Session, 'post')
    def test_connectToken(self, mock_post):
        mock_post.return_value = MockResponse(self.mock_response, 200)
        self.connection.connectToken("refresh_token")
        self.assertEqual(self.connection.access_token, "access_token")
        self.assertEqual(self.connection.refresh_token, "refresh_token")

    def test_refresh(self):
        with patch.object(requests.Session, 'post') as mock_post:
            mock_post.return_value = MockResponse(self.mock_response, 200)
            self.connection.refresh()
            self.assertEqual(self.connection.access_token, "access_token")
            self.assertEqual(self.connection.refresh_token, "refresh_token")

            mock_post.return_value = MockResponse({}, 400)
            self.assertFalse(self.connection.refresh())

    def test_checkAuth(self):
        self.assertFalse(self.connection.checkAuth())

        self.connection.access_token = "access_token"
        self.assertTrue(self.connection.checkAuth())

    @patch.object(requests.Session, 'post')
    def test_request(self, mock_post):
        mock_post.return_value = MockResponse({}, 400)

        self.assertFalse(self.connection.request("test", "label", []))

        uploads = BytesIO(b"test")
        uploads.name = "test.txt"

        mock_post.return_value = MockResponse({}, 200)
        self.connection.request("test", "label", "uploads")


if __name__ == '__main__':
    unittest.main()
