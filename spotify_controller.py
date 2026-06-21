"""Spotify Controller for Chromecast — launches Spotify app on Cast devices."""

import hashlib
import logging
import threading
from pychromecast.controllers import BaseController

APP_SPOTIFY = "CC32E753"
APP_NAMESPACE = "urn:x-cast:com.spotify.chromecast.secure.v1"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spotify_cast")


class SpotifyController(BaseController):
    def __init__(self, cast_device):
        super().__init__(APP_NAMESPACE, APP_SPOTIFY)
        self.cast_device = cast_device
        self.app_launched = False
        self.waiting = threading.Event()

    def receive_message(self, _message, data: dict):
        logger.info(f"Cast message: {data.get('type', 'unknown')}")
        # Any response from the Spotify app means it's running
        self.app_launched = True
        self.waiting.set()
        return True

    def launch_app(self, timeout=20):
        """Launch the Spotify app on the Cast device."""
        self.app_launched = False
        self.waiting.clear()

        def callback(*_):
            logger.info("Spotify app callback fired")
            self.app_launched = True
            self.waiting.set()

        logger.info(f"Launching Spotify on: {self.cast_device.cast_info.friendly_name}")
        self.launch(callback_function=callback)

        # Wait for the app to launch
        for i in range(timeout):
            if self.app_launched:
                logger.info(f"Spotify app launched after {i}s")
                return True
            self.waiting.wait(1)

        logger.warning(f"Spotify launch timed out after {timeout}s")
        return False

    def get_device_id(self):
        return hashlib.md5(
            self.cast_device.cast_info.friendly_name.encode()
        ).hexdigest()
