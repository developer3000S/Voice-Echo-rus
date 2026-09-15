"""Voice Connect subsystem.

This package adds the local gateway, device registry, pairing flow, and
protocol definitions used by Voice AI to reach companion devices.
"""

from .service import VoiceConnectService, get_service

__all__ = ["VoiceConnectService", "get_service"]
