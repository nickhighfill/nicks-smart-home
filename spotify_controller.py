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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spotify_cast")


class SpotifyController(BaseController):
    def __init__(self, cast_device, access_token, expires):
        super().__init__(APP_NAMESPACE, APP_SPOTIFY)
        self.access_token = access_token
        self.expires = expires
        self.is_launched = False
        self.device = None
        self.credential_error = False
        self.waiting = threading.Event()
        self.cast_device = cast_device

    def receive_message(self, _message, data: dict):
        logger.info(f"Cast message received: {data.get('type', 'unknown')}")

        if data["type"] == TYPE_GET_INFO_RESPONSE:
            self.device = self._get_device_id()
            self.client = data["payload"]["clientID"]
            logger.info(f"Got Cast client ID: {self.client}, device: {self.device}")

            headers = {
                "authorization": f"Bearer {self.access_token}",
                "content-type": "text/plain;charset=UTF-8",
            }
            request_body = json.dumps(
                {"clientId": self.client, "deviceId": self.device}
            )

            try:
                response = requests.post(
                    "https://spclient.wg.spotify.com/device-auth/v1/refresh",
                    headers=headers,
                    data=request_body,
                    timeout=10,
                )
                logger.info(f"Spotify device-auth response: {response.status_code}")

                if response.status_code != 200:
                    logger.error(f"Device-auth failed: {response.text}")
                    self.credential_error = True
                    self.waiting.set()
                    return True

                json_resp = response.json()

                if "accessToken" not in json_resp:
                    logger.error(f"No accessToken in device-auth response: {json_resp}")
                    self.credential_error = True
                    self.waiting.set()
                    return True

                self.send_message({
                    "type": TYPE_ADD_USER,
                    "payload": {
                        "blob": json_resp["accessToken"],
                        "tokenType": "accesstoken",
                    },
                })
                logger.info("Sent addUser to Cast device")

            except Exception as e:
                logger.error(f"Device-auth request failed: {e}")
                self.credential_error = True
                self.waiting.set()

        if data["type"] == TYPE_ADD_USER_RESPONSE:
            logger.info("addUser SUCCESS — Spotify registered on Cast device")
            self.is_launched = True
            self.waiting.set()

        if data["type"] == TYPE_ADD_USER_ERROR:
            logger.error(f"addUser ERROR: {data}")
            self.device = None
            self.credential_error = True
            self.waiting.set()

        return True

    def launch_app(self, timeout=30):
        def callback(*_):
            logger.info("Spotify app launched on Cast, sending getInfo...")
            self.send_message({
                "type": TYPE_GET_INFO,
                "payload": {
                    "remoteName": self.cast_device.cast_info.friendly_name,
                    "deviceID": self._get_device_id(),
                    "deviceAPI_isGroup": self.cast_device.cast_type == "group",
                },
            })

        self.device = None
        self.credential_error = False
        self.waiting.clear()
        logger.info(f"Launching Spotify on: {self.cast_device.cast_info.friendly_name}")
        self.launch(callback_function=callback)

        for i in range(timeout):
            if self.is_launched:
                logger.info(f"Spotify fully launched after {i}s")
                return True
            if self.credential_error:
                logger.error("Credential error during launch")
                return False
            self.waiting.wait(1)

        logger.warning(f"Spotify launch timed out after {timeout}s (is_launched={self.is_launched})")
        return self.is_launched

    def _get_device_id(self):
        return hashlib.md5(
            self.cast_device.cast_info.friendly_name.encode()
        ).hexdigest()
