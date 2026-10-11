# PD01 Printer MCP

A privacy-safe MCP server for PD01-compatible 58mm BLE thermal printers on Windows.

It exposes a confirmation-gated workflow:

1. `check_printer` checks the BLE connection without using paper.
2. `prepare_text` renders and returns a text preview without using paper.
3. `print_prepared` prints only after explicit human confirmation.
4. `disconnect_printer` closes the BLE connection without using paper.

## Why this project exists

Windows may show a PD01 as paired while the printer no longer advertises over BLE. A scanner-only client then incorrectly reports that the printer is missing. This server first opens the Windows paired-device instance and performs uncached GATT discovery, then falls back to BLE scanning.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or 3.12
- A PD01-compatible BLE printer using the 0x5178 protocol
- 58mm thermal paper

## Quick start

```powershell
git clone YOUR_REPOSITORY_URL
cd pd01-printer-mcp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python printer_server.py
```

Pair the printer once in Windows Bluetooth settings before starting. “Paired, not connected” is normal for BLE devices; the server connects when a tool is called.

The local MCP URL is:

```text
http://127.0.0.1:4176/mcp
```

Example client configuration:

```json
{
  "mcpServers": {
    "pd01-printer": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:4176/mcp"
    }
  }
}
```

See [HUMAN_GUIDE_ZH.md](HUMAN_GUIDE_ZH.md) for the Chinese human guide and [AI_GUIDE.md](AI_GUIDE.md) for the AI tool policy.

## Configuration

Configuration uses environment variables. Copy `.env.example` for reference, but set variables in your shell or service manager; this project does not automatically load `.env`.

Do not commit real Bluetooth addresses, server addresses, access tokens, private keys, logs, or print content.

## Remote access

The server listens on `127.0.0.1` by default. Keep that default unless you understand the exposure risk.

For remote AI clients, place the MCP behind an authenticated HTTPS reverse proxy, VPN, or secure tunnel. Do not expose an unauthenticated physical-printing tool directly to the internet.

## Safety model

- Status checks and preparation do not use paper.
- Printing requires an existing prepared job and the exact token `CONFIRM_PRINT`.
- AI clients must show the exact prepared text and ask the human before printing.
- AI clients must not retry a failed or uncertain print automatically.

The confirmation token is an application safety barrier, not authentication. Use real authentication for any network exposure.

## Protocol attribution

The PD01 command framing and GATT details are based on public reverse-engineering work, including [rhnvrm/catprinter](https://github.com/rhnvrm/catprinter), which is MIT licensed.

## License

MIT. See [LICENSE](LICENSE).
