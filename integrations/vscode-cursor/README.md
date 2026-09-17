# Yiyawei Local Bridge POC

This is a minimal VS Code / Cursor extension proof of concept.

It calls the local daemon:

```powershell
python app.py --daemon
```

Boundary:

- only loopback bridge URLs are accepted;
- it calls `POST /v1/process-text`;
- it does not write the clipboard or send paste keys;
- insertion is controlled by the editor extension layer;
- high-risk or confirmation-required results show a review prompt before insert.
