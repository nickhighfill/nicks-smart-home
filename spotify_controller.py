"""Spotify Controller for Chromecast — based on Spotcast's implementation."""

import hashlib
import json
import logging
import threading
import requests
from pychromecast.controllers import BaseController

APP_SPOTIFY = "CC32E753"
APP_NAMESPACE = "urn:x-cast:com.spotify.chromecast.secure.v1"
TYPE_GET_INFO = "getInfo"
TYPE_GET_INFO_RESPONSE = "getInfoResponse"
TYPE_ADD_USER = "addUser"
TYPE_ADD_USER_RESPONSE = "addUserResponse"
TYPE_ADD_USER_ERROR = "addUserError"


class SpotifyController(BaseController):
    def __init__(self, cast_device, access_token, expires):
        super().__init__(APP_NAMESPACE, APP_SPOTIFY)
        self.logger = logging.getLogger(__name__)
        self.access_token = access_token
        self.expires = expires
        self.is_launched = False
        self.device = None
        self.credential_error = False
        self.waiting = threading.Event()
        self.cast_device = cast_device

    def receive_message(self, _message, data: dict):
        if data["type"] == TYPE_GET_INFO_RESPONSE:
            self.device = self._get_device_id()
            self.client = data["payload"]["clientID"]
            headers = {
                "authorization": f"Bearer {self.access_token}",
                "content-type": "text/plain;charset=UTF-8",
            }
            request_body = json.dumps(
                {"clientId": self.client, "deviceId": self.device}
            )
            response = requests.post(
                "https://spclient.wg.spotify.com/device-auth/v1/refresh",
                headers=headers,
                data=request_body,
            )
            json_resp = response.json()
            self.send_message({
                "type": TYPE_ADD_USER,
                "payload": {
                    "blob": json_resp["accessToken"],
                    "tokenType": "accesstoken",
                },
            })

        if data["type"] == TYPE_ADD_USER_RESPONSE:
            self.is_launched = True
            self.waiting.set()

        if data["type"] == TYPE_ADD_USER_ERROR:
            self.device = None
            self.credential_error = True
            self.waiting.set()

        return True

    def launch_app(self, timeout=20):
        def callback(*_):
            self.send_message({
                "type": TYPE_GET_INFO,
                "payload": {
                    "remoteName": self.cast_device.cast_info.friendly_name,
                    "deviceID": self._get_device_id(),
                    "deviceAPI_isGroup": False,
                },
            })

        self.device = None
        self.credential_error = False
        self.waiting.clear()
        self.launch(callback_function=callback)

        for _ in range(timeout):
            if self.is_launched:
                return True
            self.waiting.wait(1)

        if self.credential_error:
            self.logger.error("Spotify credential error on Cast device")
            return False

        # Known issue: is_launched can stay False even when it worked
        self.logger.warning("Spotify launch timeout — may still work")
        return False

    def _get_device_id(self):
        return hashlib.md5(
            self.cast_device.cast_info.friendly_name.encode()
        ).hexdigest()
