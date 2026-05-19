"""WebUI-only persisted state and helpers.

This package owns metadata that is meaningful only to the embedded WebUI
(sidebar pin/archive overrides, view preferences, etc.) and that must not
affect agent sessions. The runtime never touches these files; the WebSocket
channel exposes them through dedicated envelopes.
"""
