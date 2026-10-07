"""qa-security mock harness (Wave 2, AGENT_RULES §5: mocks only, isolated).

- mock_openai: scripted OpenAI-compatible provider (tool-call scripts, 429s,
  malformed JSON) on an ephemeral 127.0.0.1 port — never a real provider.
- wssession: shared TestClient WS session helpers (auth, timed recv, drain).
- mock_body: role=body client implementing act_req handlers.
- mock_orb: role=ui client recording orb_state sequences.
- voicespy: class-level TTS/STT mocks (never spawn Fish, never load Whisper).
- brain_subprocess: hermetic brain subprocess for the two-instance test.
"""
