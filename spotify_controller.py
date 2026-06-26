"""Spotify Controller for Chromecast — launches Spotify app on Cast devices."""

import logging
import threading
from pychromecast.controllers import BaseController

APP_SPOTIFY = "CC32E753"
APP_NAMESPACE = "urn:x-cast:com.spotify.chromecast.secure.v1"

logger = logging.getLogger(__name__)


class SpotifyController(BaseController):
    def __init__(self, cast_device):
        super().__init__(APP_NAMESPACE, APP_SPOTIFY)
        self.cast_device = cast_device
        self.app_launched = False
        self.waiting = threading.Event()
        self._launch_error = None

    def receive_message(self, _message, data: dict):
        msg_type = data.get("type", "unknown")
        logger.info(f"Cast message: {msg_type}")

        # Error messages don't count as a successful launch
        if msg_type in ("error", "INVALID_REQUEST", "LAUNCH_ERROR"):
            logger.warning(f"Received error message from Cast: {data}")
            self._launch_error = data.get("message", msg_type)
            self.waiting.set()
            return True

        # Actual success indicator
        self.app_launched = True
        self.waiting.set()
        return True

    def launch_app(self, timeout=20):
        """Launch the Spotify app on the Cast device.

        Returns dict with 'success' bool and 'error' string (if failed).
        """
        self._reset_state()

        friendly_name = self.cast_device.cast_info.friendly_name
        logger.info(f"Launching Spotify on: {friendly_name}")

        try:
            def callback(*_):
                logger.info("Spotify app callback fired")
                if not self._launch_error:
                    self.app_launched = True
                self.waiting.set()

            self.launch(callback_function=callback)
        except Exception as e:
            logger.error(f"Failed to send launch command: {e}")
            return {"success": False, "error": f"Launch command failed: {e}"}

        # Single blocking wait instead of a polling loop
        launched = self.waiting.wait(timeout=timeout)

        if not launched:
            logger.warning(f"Spotify launch timed out after {timeout}s")
            self._reset_state()
            return {"success": False, "error": "Timed out waiting for Spotify to launch"}

        if self._launch_error:
            error = self._launch_error
            logger.warning(f"Spotify launch failed: {error}")
            self._reset_state()
            return {"success": False, "error": error}

        if self.app_launched:
            logger.info("Spotify app launched successfully")
            return {"success": True, "error": None}

        self._reset_state()
        return {"success": False, "error": "Unknown launch failure"}

    def is_connected(self):
        """Check if the Cast device is reachable and Spotify is running."""
        try:
            status = self.cast_device.status
            if status is None:
                return False
            app_id = self.cast_device.app_id
            return app_id == APP_SPOTIFY
        except Exception as e:
            logger.debug(f"Connection check failed: {e}")
            return False

    def stop_app(self):
        """Stop the Spotify app on the Cast device."""
        try:
            self.cast_device.quit_app()
            self._reset_state()
            logger.info("Spotify app stopped")
        except Exception as e:
            logger.error(f"Failed to stop Spotify app: {e}")

    def _reset_state(self):
        """Reset internal state for a fresh launch attempt."""
        self.app_launched = False
        self._launch_error = None
        self.waiting.clear()
