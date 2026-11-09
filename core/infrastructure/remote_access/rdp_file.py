"""
RDP file generation utility.

Creates an in-memory `.rdp` file for remote desktop connections to lab computers.
"""
from __future__ import annotations

import io

BASE_RDP_CONTENT = b"""\
screen mode id:i:2
use multimon:i:0
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
winposstr:s:0,1,0,0,1238,606
compression:i:1
keyboardhook:i:2
audiocapturemode:i:0
videoplaybackmode:i:1
connection type:i:7
networkautodetect:i:1
bandwidthautodetect:i:1
displayconnectionbar:i:1
enableworkspacereconnect:i:0
disable wallpaper:i:0
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
audiomode:i:0
redirectprinters:i:1
redirectcomports:i:0
redirectsmartcards:i:1
redirectclipboard:i:1
redirectposdevices:i:0
autoreconnection enabled:i:1
authentication level:i:2
prompt for credentials:i:0
negotiate security layer:i:1
remoteapplicationmode:i:0
alternate shell:s:
shell working directory:s:
gatewayhostname:s:
gatewayusagemethod:i:4
gatewaycredentialssource:i:4
gatewayprofileusagemethod:i:0
promptcredentialonce:i:0
gatewaybrokeringtype:i:0
use redirection server name:i:0
rdgiskdcproxy:i:0
kdcproxyname:s:
drivestoredirect:s:"""


def _sanitize(value: str) -> str:
    """Strip newline characters to prevent RDP directive injection (OWASP A03)."""
    return value.replace("\r", "").replace("\n", "")


def create_rdp_file(computer_name: str | None, technical_user: object | None) -> io.BytesIO:
    """
    Build an RDP configuration file as an in-memory bytes buffer.

    Args:
        computer_name:  The target computer hostname/IP.
        technical_user: Object with a `.username` attribute (or None).

    Returns:
        io.BytesIO positioned at offset 0, ready for file storage.
    """
    raw_username = technical_user.username if technical_user and hasattr(technical_user, "username") else ""
    raw_address = computer_name or ""

    username_line = f"\nusername:s:{_sanitize(raw_username)}".encode("utf-8")
    address_line = f"\nfull address:s:{_sanitize(raw_address)}".encode("utf-8")

    content = BASE_RDP_CONTENT + address_line + username_line

    buf = io.BytesIO()
    buf.write(content)
    buf.seek(0)
    return buf
