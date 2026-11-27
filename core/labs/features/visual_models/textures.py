"""Deterministic procedural PNG faceplate & LCD textures for Lab Mango 3D reference models.

All textures are rendered in-memory via Pillow (a core backend dependency) and embedded directly
into self-contained GLB v2 binary chunks with zero external URLs or runtime assets.
"""

from __future__ import annotations

import functools
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)
_FONT_CANDIDATES_REG = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_FONT_CANDIDATES_MONO = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
)


@functools.lru_cache(maxsize=64)
def _font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = _FONT_CANDIDATES_MONO if mono else (_FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REG)
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_vector_logo(
    draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0, *, text_fill: tuple[int, int, int] = (35, 38, 44)
) -> None:
    """Crisp VECTOR wordmark with signature crimson chevron arrow."""
    f = _font(int(36 * scale), bold=True)
    draw.text((x, y), "VECTOR", fill=text_fill, font=f)
    cx = x + int(172 * scale)
    cy = y + int(20 * scale)
    r = int(20 * scale)
    pts_outer = [
        (cx, cy - r),
        (cx + int(34 * scale), cy),
        (cx, cy + r),
        (cx, cy + int(11 * scale)),
        (cx + int(19 * scale), cy),
        (cx, cy - int(11 * scale)),
    ]
    draw.polygon(pts_outer, fill=(196, 16, 46))


# --- Vector & Lauterbach automotive interfaces -------------------------------------------------------------


@functools.lru_cache(maxsize=32)
def tex_vn1630a_top() -> bytes:
    """Vector VN1630A white top faceplate with grey/crimson bands and 5 labeled LEDs."""
    w, h = 640, 500
    img = Image.new("RGB", (w, h), (242, 244, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(205, 210, 216), width=4)
    _draw_vector_logo(d, 56, 44, scale=1.05)
    d.rectangle([48, 134, w - 48, 236], fill=(122, 126, 132))
    d.text((70, 152), "VN1630A", fill=(250, 251, 252), font=_font(62, bold=True))
    d.rectangle([48, 236, w - 48, 314], fill=(196, 16, 46))
    d.text((70, 254), "CAN/LIN Interface", fill=(252, 252, 253), font=_font(38, bold=True))
    labels = ("CH1", "CH2", "CH3", "CH4", "Status")
    led_fills = ((40, 210, 110), (40, 210, 110), (240, 175, 35), (40, 210, 110), (50, 220, 125))
    f_lbl = _font(18, bold=False)
    for i, (lbl, fill) in enumerate(zip(labels, led_fills, strict=True)):
        lx = 305 + i * 68
        ly = 398
        d.ellipse([lx - 9, ly - 9, lx + 9, ly + 9], fill=(175, 180, 186), outline=(130, 136, 142), width=2)
        d.ellipse([lx - 5, ly - 5, lx + 5, ly + 5], fill=fill)
        d.text((lx - 18 if lbl != "Status" else lx - 26, ly + 18), lbl, fill=(95, 100, 108), font=f_lbl)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_vn1630a_front() -> bytes:
    """Vector VN1630A matte-black front plate with crisp CH2/4, CH1/3, Sync labels."""
    w, h = 640, 192
    img = Image.new("RGB", (w, h), (22, 25, 30))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, w - 5, h - 5], outline=(42, 46, 54), width=3)
    f = _font(26, bold=True)
    d.text((132, 20), "CH2/4", fill=(232, 236, 240), font=f)
    d.text((332, 20), "CH1/3", fill=(232, 236, 240), font=f)
    d.text((506, 20), "Sync", fill=(232, 236, 240), font=f)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_vn5620_top() -> bytes:
    """Vector VN5620 white top faceplate with bold crimson banner, BroadR-Reach specs & ETH/CAN legend."""
    w, h = 640, 620
    img = Image.new("RGB", (w, h), (242, 244, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(205, 210, 216), width=4)
    _draw_vector_logo(d, 58, 42, scale=1.08)
    d.rectangle([42, 134, w - 42, 314], fill=(196, 16, 46))
    d.text((76, 162), "VN5620", fill=(252, 252, 253), font=_font(64, bold=True))
    d.text((76, 246), "Ethernet/CAN Interface", fill=(246, 238, 240), font=_font(30, bold=False))
    specs = ("BroadR-Reach\u00ae", "100BASE-T1", "1000BASE-T1", "100BASE-TX", "1000BASE-T")
    f_spec = _font(21, bold=True)
    for i, line in enumerate(specs):
        d.text((72, 344 + i * 26), line, fill=(58, 64, 72), font=f_spec)
    f_s = _font(19, bold=True)
    f_m = _font(17, bold=True)
    for i in range(4):
        ex = 114 + i * 74 + (14 if i >= 2 else 0)
        d.text((ex - 7, 502), "M", fill=(90, 96, 104), font=f_m)
        d.ellipse([ex - 7, 530, ex + 7, 544], fill=(42, 215, 115), outline=(120, 126, 132), width=2)
        d.text((ex - 5, 560), str(i + 1), fill=(52, 58, 66), font=f_s)
    d.text((54, 560), "ETH", fill=(52, 58, 66), font=f_s)
    d.text((406, 560), "CAN", fill=(52, 58, 66), font=f_s)
    for i in range(2):
        cx = 468 + i * 48
        d.ellipse([cx - 7, 530, cx + 7, 544], fill=(240, 175, 35), outline=(120, 126, 132), width=2)
        d.text((cx - 5, 560), str(5 + i), fill=(52, 58, 66), font=f_s)
    d.ellipse([562, 514, 584, 536], outline=(85, 92, 100), width=2)
    d.ellipse([566, 518, 580, 532], fill=(42, 215, 115))
    d.ellipse([562, 552, 584, 574], outline=(85, 92, 100), width=2)
    d.ellipse([566, 556, 580, 570], fill=(245, 248, 250))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_vn5620_front() -> bytes:
    """Vector VN5620 matte-black front bezel with ETH 1..4 and CAN 5/6 silkscreen."""
    w, h = 640, 180
    img = Image.new("RGB", (w, h), (22, 25, 30))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, w - 5, h - 5], outline=(42, 46, 54), width=3)
    f = _font(21, bold=True)
    for i in range(4):
        d.text((66 + i * 94, 18), f"ETH {i + 1}", fill=(228, 232, 238), font=f)
    d.text((488, 18), "CAN 5/6", fill=(228, 232, 238), font=f)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_vt_system_front() -> bytes:
    """Vector VT System VT8012A 3U modular HIL chassis faceplate with 8 labeled VT blades."""
    w, h = 960, 290
    img = Image.new("RGB", (w, h), (28, 32, 38))
    d = ImageDraw.Draw(img)
    # Top Vector header bar with crimson accent stripe.
    d.rectangle([0, 0, w, 46], fill=(22, 26, 32))
    d.rectangle([0, 46, w, 54], fill=(196, 16, 46))
    _draw_vector_logo(d, 20, 8, scale=0.72, text_fill=(238, 242, 246))
    d.text(
        (220, 13), "VT SYSTEM  ·  VT8012A Modular HIL Test Chassis", fill=(208, 216, 226), font=_font(18, bold=True)
    )
    d.text((826, 15), "CANoe RT", fill=(240, 190, 60), font=_font(16, bold=True))
    # 8 individual brushed-aluminum VT modular card blades.
    blades = (
        ("VT6051A", "RT PC", (45, 215, 115)),
        ("VT1004A", "LOAD", (45, 215, 115)),
        ("VT2004A", "STIM", (45, 215, 115)),
        ("VT2516A", "DIG I/O", (245, 180, 40)),
        ("VT2848", "GP I/O", (45, 215, 115)),
        ("VT6104B", "CAN-FD", (55, 205, 245)),
        ("VT6306B", "ETH T1", (55, 205, 245)),
        ("VT7001A", "POWER", (235, 75, 75)),
    )
    f_code = _font(15, bold=True)
    f_sub = _font(12, bold=True)
    card_w = 114
    for idx, (code, role, led_col) in enumerate(blades):
        x0 = 16 + idx * 116
        d.rectangle([x0, 62, x0 + card_w - 4, h - 14], fill=(196, 202, 210), outline=(72, 78, 88), width=2)
        d.rectangle([x0 + 2, 64, x0 + card_w - 6, 94], fill=(38, 44, 54))
        d.text((x0 + 10, 71), code, fill=(242, 246, 250), font=f_code)
        d.text((x0 + 14, 102), role, fill=(42, 48, 56), font=f_sub)
        # Status LED pair.
        d.ellipse([x0 + 16, 124, x0 + 26, 134], fill=led_col, outline=(62, 68, 76), width=1)
        d.ellipse([x0 + 36, 124, x0 + 46, 134], fill=(45, 215, 115), outline=(62, 68, 76), width=1)
        # Green Phoenix contact terminal strip graphic on lower half.
        d.rectangle([x0 + 16, 150, x0 + card_w - 20, h - 32], fill=(28, 122, 58), outline=(18, 82, 38), width=2)
        for p in range(6):
            py = 158 + p * 17
            d.ellipse([x0 + 26, py, x0 + 36, py + 10], fill=(195, 202, 208), outline=(42, 48, 54), width=1)
            d.rectangle([x0 + 44, py + 1, x0 + card_w - 28, py + 9], fill=(22, 32, 26))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_lauterbach_top() -> bytes:
    """Lauterbach TRACE32 PowerDebug pearl-white top deck with crisp LED legends, wordmark & port silkscreen."""
    w, h = 480, 920
    img = Image.new("RGB", (w, h), (234, 236, 239))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, w - 12, h - 12], radius=16, outline=(202, 206, 212), width=3)
    f_sm = _font(20, bold=True)
    f_xs = _font(17, bold=True)
    d.text((394, 42), "CE", fill=(72, 78, 86), font=f_sm)
    d.text((84, 72), "A", fill=(52, 58, 66), font=f_sm)
    d.text((84, 168), "B", fill=(52, 58, 66), font=f_sm)
    d.text((126, 122), "TRACE32  DEBUG / TRACE", fill=(62, 68, 76), font=f_xs)
    d.rectangle([62, 286, w - 62, 620], fill=(208, 212, 218), outline=(172, 178, 186), width=2)
    d.text((136, 642), "LAUTERBACH", fill=(32, 36, 42), font=_font(30, bold=True))
    d.text((140, 678), "POWERDEBUG  USB 3.0", fill=(68, 74, 84), font=_font(17, bold=True))
    leds = (
        ("POWER", (32, 195, 92), 728),
        ("RUNNING", (235, 155, 20), 762),
        ("DEBUG", (38, 165, 235), 796),
    )
    for label, color, ly in leds:
        d.ellipse([90, ly, 108, ly + 18], fill=color, outline=(62, 68, 76), width=2)
        d.text((122, ly - 1), label, fill=(38, 42, 48), font=f_xs)
    d.line([84, 872, 392, 872], fill=(110, 116, 126), width=2)
    d.ellipse([96, 844, 122, 870], outline=(62, 68, 76), width=2)
    d.text((130, 848), "DBG", fill=(45, 50, 58), font=f_xs)
    d.text((212, 848), "USB", fill=(45, 50, 58), font=f_xs)
    d.ellipse([300, 844, 326, 870], outline=(62, 68, 76), width=2)
    d.text((334, 840), "POWER", fill=(45, 50, 58), font=_font(15, bold=True))
    d.text((334, 858), "5.0 V", fill=(65, 72, 80), font=_font(14, bold=True))
    return _to_png(img)


# --- Debuggers & logic analyzers (Saleae Logic Pro 16, SEGGER J-Link PRO) ----------------------------------


@functools.lru_cache(maxsize=32)
def tex_saleae_logic_top() -> bytes:
    """Saleae Logic Pro 16 sleek anodized charcoal aluminum pod top silkscreen."""
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (34, 38, 44))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, w - 12, h - 12], radius=24, fill=(38, 42, 50), outline=(66, 74, 86), width=3)
    # Subtle brushed diagonal highlight stripe.
    d.line([36, 98, w - 36, 98], fill=(64, 72, 84), width=2)
    d.text((48, 40), "SALEAE", fill=(238, 244, 250), font=_font(38, bold=True))
    d.text((246, 48), "LOGIC PRO 16", fill=(95, 198, 245), font=_font(28, bold=True))
    d.text((48, 124), "16-Channel Digital & Analog Logic Analyzer", fill=(176, 186, 200), font=_font(20, bold=False))
    d.text(
        (48, 156), "500 MS/s Digital  ·  50 MS/s Analog  ·  USB 3.0", fill=(132, 144, 160), font=_font(17, bold=True)
    )
    # Subtle minimalist Saleae waveform emblem center.
    pts = [
        (64, 256),
        (138, 256),
        (138, 208),
        (222, 208),
        (222, 286),
        (312, 286),
        (312, 224),
        (410, 224),
        (410, 256),
        (576, 256),
    ]
    d.line(pts, fill=(68, 185, 240), width=4)
    # Status RGB LED dot.
    d.ellipse([546, 48, 566, 68], fill=(45, 215, 120), outline=(140, 150, 162), width=2)
    # Front-edge pinout silkscreen above the 2x8 headers (+Z bottom).
    d.line([36, 368, w - 36, 368], fill=(64, 72, 84), width=2)
    f_ch = _font(17, bold=True, mono=True)
    for i in range(8):
        d.text((54 + i * 32, 386), str(i), fill=(224, 232, 240), font=f_ch)
        d.text((342 + i * 32, 386), str(i + 8), fill=(224, 232, 240), font=f_ch)
    d.text((104, 422), "CH 0 - 7   (GND BELOW)", fill=(142, 154, 170), font=_font(16, bold=True))
    d.text((388, 422), "CH 8 - 15  (GND BELOW)", fill=(142, 154, 170), font=_font(16, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_segger_jlink_top() -> bytes:
    """SEGGER J-Link PRO iconic emerald-green & white top label on matte-black debugger."""
    w, h = 640, 420
    img = Image.new("RGB", (w, h), (22, 25, 30))
    d = ImageDraw.Draw(img)
    # White & SEGGER emerald-green rounded decal inlay.
    d.rounded_rectangle([24, 24, w - 24, h - 24], radius=24, fill=(244, 247, 249), outline=(42, 48, 56), width=4)
    # Signature diagonal green upper banner.
    d.rectangle([28, 28, w - 28, 178], fill=(14, 138, 68))
    d.text((56, 52), "SEGGER", fill=(252, 254, 253), font=_font(54, bold=True))
    d.text((58, 120), "It simply works!", fill=(208, 244, 222), font=_font(22, bold=True))
    # Main J-Link PRO designation.
    d.text((56, 206), "J-Link PRO", fill=(24, 30, 38), font=_font(52, bold=True))
    d.text((58, 274), "JTAG / SWD  ·  USB & 100M Ethernet Debug Probe", fill=(72, 80, 92), font=_font(20, bold=True))
    # Bottom status LED legends & URL.
    d.line([54, 326, w - 54, 326], fill=(195, 204, 212), width=2)
    d.ellipse([60, 344, 80, 364], fill=(42, 215, 110), outline=(72, 80, 88), width=2)
    d.text((92, 344), "TARGET / LINK", fill=(58, 66, 76), font=_font(17, bold=True))
    d.text((394, 344), "www.segger.com", fill=(14, 138, 68), font=_font(19, bold=True))
    return _to_png(img)


# --- Power supplies, Electronic Load, DMM, Oscilloscope, AWG, RF Spectrum Analyzer -------------------------


@functools.lru_cache(maxsize=32)
def tex_keysight_psu_front() -> bytes:
    """Keysight E36312A triple-output programmable DC power supply front bezel & 4.3-inch TFT."""
    w, h = 840, 460
    img = Image.new("RGB", (w, h), (38, 42, 48))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=16, fill=(46, 51, 59), outline=(92, 98, 110), width=4)
    # Keysight signature top header with subtle crimson accent pulse bar.
    d.rectangle([28, 22, 168, 28], fill=(214, 28, 48))
    d.text((28, 34), "KEYSIGHT", fill=(238, 242, 248), font=_font(24, bold=True))
    d.text(
        (178, 36), "E36312A   Triple Output Programmable DC Supply", fill=(184, 194, 208), font=_font(18, bold=True)
    )
    # Bright 4.3-inch color TFT bay.
    d.rounded_rectangle([28, 72, 476, 304], radius=8, fill=(8, 13, 22), outline=(22, 26, 32), width=4)
    d.rectangle([34, 78, 470, 102], fill=(22, 32, 48))
    d.text((44, 82), "3-CH TRACKING   OVP/OCP ARMED   LAN · USB", fill=(185, 210, 236), font=_font(14, bold=True))
    cols = (
        (40, "1", "06.000", "0.850", "5.10 W", (252, 212, 48), "CV"),
        (184, "2", "+25.00", "0.420", "10.5 W", (65, 232, 128), "CV"),
        (328, "3", "-25.00", "0.120", "3.00 W", (58, 218, 248), "CV"),
    )
    for x0, ch, v_txt, a_txt, w_txt, col, mode in cols:
        d.rounded_rectangle([x0, 110, x0 + 134, 270], radius=6, fill=(14, 22, 34), outline=col, width=2)
        d.rectangle([x0 + 2, 112, x0 + 132, 136], fill=col)
        d.text((x0 + 10, 115), f"CH {ch}", fill=(12, 16, 22), font=_font(16, bold=True))
        d.text((x0 + 96, 116), mode, fill=(12, 16, 22), font=_font(15, bold=True))
        d.text((x0 + 10, 148), v_txt, fill=col, font=_font(24, bold=True, mono=True))
        d.text((x0 + 110, 156), "V", fill=(180, 195, 210), font=_font(14, bold=True))
        d.text((x0 + 14, 192), a_txt, fill=(238, 244, 250), font=_font(22, bold=True, mono=True))
        d.text((x0 + 110, 200), "A", fill=(180, 195, 210), font=_font(14, bold=True))
        d.text((x0 + 16, 236), w_txt, fill=(148, 168, 190), font=_font(15, bold=True, mono=True))
    for i, lbl in enumerate(("Meter", "Track", "List", "Log", "Store", "Util")):
        sx = 40 + i * 72
        d.rectangle([sx, 276, sx + 64, 296], fill=(32, 46, 68))
        d.text((sx + 10, 279), lbl, fill=(215, 228, 242), font=_font(13, bold=True))
    # Right rotary dials & channel buttons.
    d.ellipse([508, 102, 608, 202], fill=(28, 32, 38), outline=(105, 114, 126), width=3)
    d.text((524, 212), "VOLTAGE", fill=(180, 190, 204), font=_font(14, bold=True))
    d.ellipse([636, 102, 736, 202], fill=(28, 32, 38), outline=(105, 114, 126), width=3)
    d.text((652, 212), "CURRENT", fill=(180, 190, 204), font=_font(14, bold=True))
    for i, (lbl, col) in enumerate(
        (("ALL ON", (42, 185, 95)), ("CH1", (252, 212, 48)), ("CH2", (65, 232, 128)), ("CH3", (58, 218, 248)))
    ):
        bx = 508 + i * 76
        d.rounded_rectangle([bx, 252, bx + 66, 292], radius=5, fill=(64, 72, 84), outline=col, width=2)
        d.text((bx + 10 if len(lbl) > 3 else bx + 16, 263), lbl, fill=(242, 246, 250), font=_font(14, bold=True))
    # Bottom terminal legends.
    d.line([28, 326, w - 28, 326], fill=(84, 92, 106), width=2)
    d.text((40, 336), "POWER", fill=(186, 196, 210), font=_font(14, bold=True))
    d.text((192, 336), "CH1  6V / 5A", fill=(252, 212, 48), font=_font(15, bold=True))
    d.text((388, 336), "GND", fill=(110, 225, 145), font=_font(15, bold=True))
    d.text((488, 336), "CH2  +25V / 1A", fill=(65, 232, 128), font=_font(15, bold=True))
    d.text((674, 336), "CH3  -25V", fill=(58, 218, 248), font=_font(15, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_rigol_dp831_front() -> bytes:
    """Rigol DP831A/DP831 triple-output programmable DC power supply front bezel & color TFT."""
    w, h = 800, 460
    img = Image.new("RGB", (w, h), (42, 46, 54))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=18, fill=(52, 57, 66), outline=(88, 95, 108), width=4)
    d.text((34, 22), "RIGOL", fill=(235, 240, 248), font=_font(30, bold=True))
    d.text((152, 28), "DP831", fill=(245, 195, 45), font=_font(24, bold=True))
    d.text((248, 31), "Programmable DC Power Supply", fill=(168, 178, 192), font=_font(18, bold=False))
    d.rounded_rectangle([32, 68, 434, 304], radius=8, fill=(10, 16, 26), outline=(22, 26, 32), width=4)
    d.rectangle([38, 74, 428, 100], fill=(24, 38, 60))
    d.text((48, 79), "CH1: +8V/5A   CH2: +30V/2A   CH3: -30V/2A", fill=(185, 215, 245), font=_font(14, bold=True))
    ch_specs = (
        (44, "CH1", "+08.000", "0.500", "4.00W", (250, 210, 55), True),
        (172, "CH2", "+12.000", "1.250", "15.0W", (65, 225, 245), True),
        (300, "CH3", "-12.000", "0.000", "0.00W", (235, 105, 195), False),
    )
    for x0, ch, volts, amps, watts, col, on in ch_specs:
        d.rounded_rectangle([x0, 108, x0 + 120, 266], radius=6, fill=(18, 28, 44), outline=col, width=2)
        d.rectangle([x0 + 2, 110, x0 + 118, 134], fill=col)
        d.text((x0 + 8, 114), ch, fill=(12, 16, 24), font=_font(16, bold=True))
        d.text((x0 + 78, 115), "ON" if on else "OFF", fill=(12, 16, 24), font=_font(14, bold=True))
        d.text((x0 + 8, 146), volts, fill=col, font=_font(22, bold=True, mono=True))
        d.text((x0 + 96, 152), "V", fill=(175, 190, 210), font=_font(14, bold=True))
        d.text((x0 + 12, 188), amps, fill=(235, 242, 250), font=_font(20, bold=True, mono=True))
        d.text((x0 + 96, 194), "A", fill=(175, 190, 210), font=_font(14, bold=True))
        d.text((x0 + 14, 232), watts, fill=(140, 165, 190), font=_font(15, bold=True, mono=True))
    for i, lbl in enumerate(("Store", "Timer", "OCP", "OVP", "Utility")):
        sx = 44 + i * 76
        d.rectangle([sx, 274, sx + 68, 296], fill=(34, 52, 78))
        d.text((sx + 10, 278), lbl, fill=(215, 230, 245), font=_font(13, bold=True))
    d.ellipse([468, 102, 570, 204], fill=(32, 36, 42), outline=(105, 115, 128), width=3)
    d.text((488, 214), "ADJUST", fill=(175, 185, 198), font=_font(14, bold=True))
    keys = (("7", "8", "9"), ("4", "5", "6"), ("1", "2", "3"), (".", "0", "OK"))
    for r, row in enumerate(keys):
        for c, k in enumerate(row):
            kx = 602 + c * 52
            ky = 92 + r * 44
            d.rounded_rectangle(
                [kx, ky, kx + 42, ky + 34], radius=5, fill=(76, 84, 96), outline=(115, 124, 138), width=1
            )
            d.text((kx + 14 if len(k) == 1 else kx + 8, ky + 8), k, fill=(242, 246, 252), font=_font(16, bold=True))
    d.line([32, 326, w - 32, 326], fill=(82, 90, 104), width=2)
    d.text((46, 336), "POWER", fill=(185, 195, 208), font=_font(14, bold=True))
    d.text((196, 336), "CH1  +8V / 5A", fill=(250, 210, 55), font=_font(15, bold=True))
    d.text((386, 336), "GND", fill=(110, 225, 145), font=_font(15, bold=True))
    d.text((484, 336), "CH2  +30V / 2A", fill=(65, 225, 245), font=_font(15, bold=True))
    d.text((640, 336), "CH3  -30V", fill=(235, 105, 195), font=_font(15, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_toellner_8952_front() -> bytes:
    """Toellner TOE 8952 low-profile German laboratory DC power supply front panel."""
    w, h = 960, 310
    img = Image.new("RGB", (w, h), (222, 224, 226))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, w - 6, h - 6], radius=10, fill=(216, 219, 222), outline=(145, 150, 158), width=4)
    d.rectangle([18, 16, w - 18, 56], fill=(38, 44, 54))
    d.text((34, 24), "TOELLNER", fill=(245, 248, 252), font=_font(24, bold=True))
    d.text((206, 26), "TOE 8952", fill=(248, 195, 45), font=_font(22, bold=True))
    d.text((352, 28), "Laboratory Power Supply   0 - 32 V / 0 - 5 A", fill=(190, 200, 212), font=_font(17, bold=False))
    d.rounded_rectangle([24, 72, 464, 228], radius=8, fill=(18, 22, 28), outline=(72, 78, 88), width=3)
    d.rectangle([38, 88, 232, 180], fill=(8, 18, 12), outline=(42, 54, 48), width=2)
    d.text((50, 106), "13.80", fill=(65, 245, 125), font=_font(50, bold=True, mono=True))
    d.text((204, 144), "V", fill=(115, 225, 150), font=_font(22, bold=True))
    d.text((42, 190), "VOLTAGE  U [V]      CV", fill=(155, 225, 175), font=_font(15, bold=True))
    d.ellipse([212, 192, 226, 206], fill=(55, 235, 115))
    d.rectangle([254, 88, 448, 180], fill=(18, 12, 6), outline=(54, 46, 38), width=2)
    d.text((266, 106), "02.45", fill=(255, 180, 42), font=_font(50, bold=True, mono=True))
    d.text((422, 144), "A", fill=(235, 185, 95), font=_font(22, bold=True))
    d.text((258, 190), "CURRENT  I [A]      CC", fill=(230, 195, 130), font=_font(15, bold=True))
    d.ellipse([428, 192, 442, 206], fill=(90, 75, 50))
    for cx, title in ((560, "VOLTAGE"), (710, "CURRENT")):
        d.arc([cx - 50, 96, cx + 50, 196], start=135, end=405, fill=(75, 82, 92), width=3)
        d.text((cx - 38, 206), title, fill=(45, 50, 58), font=_font(16, bold=True))
    for i, lbl in enumerate(("OUTPUT", "OVP", "SENSE", "LOCAL")):
        bx = 816
        by = 78 + i * 38
        d.rounded_rectangle([bx, by, bx + 114, by + 28], radius=4, fill=(68, 76, 88), outline=(42, 48, 56), width=2)
        d.text((bx + 20, by + 6), lbl, fill=(238, 242, 248), font=_font(14, bold=True))
    d.line([24, 242, w - 24, 242], fill=(140, 146, 156), width=2)
    d.text((48, 254), "POWER", fill=(48, 54, 62), font=_font(15, bold=True))
    d.text((532, 254), "+ SENSE", fill=(185, 32, 42), font=_font(15, bold=True))
    d.text((642, 254), "+ OUT", fill=(185, 32, 42), font=_font(16, bold=True))
    d.text((734, 254), "PE", fill=(35, 138, 65), font=_font(16, bold=True))
    d.text((814, 254), "- OUT", fill=(35, 42, 52), font=_font(16, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_dc_load_front() -> bytes:
    """ITECH IT8511A+ / Rigol DL3021 Programmable DC Electronic Load front panel."""
    w, h = 840, 420
    img = Image.new("RGB", (w, h), (34, 38, 44))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=14, fill=(40, 45, 52), outline=(84, 92, 104), width=4)
    d.text((30, 22), "ITECH", fill=(242, 246, 250), font=_font(26, bold=True))
    d.text(
        (132, 25),
        "IT8512A+   Programmable DC Electronic Load   150V / 30A / 300W",
        fill=(176, 188, 204),
        font=_font(17, bold=True),
    )
    # Bright VFD/TFT telemetry screen upper-left.
    d.rounded_rectangle([28, 62, 476, 258], radius=8, fill=(8, 16, 22), outline=(62, 74, 88), width=3)
    d.rectangle([34, 68, 470, 96], fill=(18, 44, 56))
    d.text(
        (46, 73),
        "CC MODE   ·   INPUT ON   ·   SENSE INT   ·   RANGE 30A",
        fill=(110, 232, 245),
        font=_font(14, bold=True),
    )
    d.text((46, 112), "12.002", fill=(68, 242, 175), font=_font(44, bold=True, mono=True))
    d.text((226, 132), "V", fill=(125, 225, 190), font=_font(22, bold=True))
    d.text((274, 112), "05.000", fill=(252, 198, 52), font=_font(44, bold=True, mono=True))
    d.text((442, 132), "A", fill=(235, 195, 98), font=_font(22, bold=True))
    d.line([42, 178, 462, 178], fill=(32, 54, 68), width=2)
    d.text((48, 194), "60.01 W", fill=(95, 212, 248), font=_font(30, bold=True, mono=True))
    d.text((246, 194), "2.400 \u03a9", fill=(210, 224, 240), font=_font(30, bold=True, mono=True))
    # Mode key cluster below screen.
    for i, (lbl, active) in enumerate(
        (("CC", True), ("CV", False), ("CR", False), ("CP", False), ("TRAN", False), ("LIST", False))
    ):
        bx = 30 + i * 74
        d.rounded_rectangle(
            [bx, 276, bx + 64, 314],
            radius=5,
            fill=(36, 128, 168) if active else (62, 70, 82),
            outline=(112, 122, 136),
            width=2,
        )
        d.text((bx + 12 if len(lbl) > 2 else bx + 20, 286), lbl, fill=(246, 250, 252), font=_font(15, bold=True))
    # Right keypad + ON/OFF illuminated button legend.
    keys = (("7", "8", "9"), ("4", "5", "6"), ("1", "2", "3"), (".", "0", "ENT"))
    for r, row in enumerate(keys):
        for c, k in enumerate(row):
            kx = 626 + c * 58
            ky = 74 + r * 46
            d.rounded_rectangle(
                [kx, ky, kx + 48, ky + 36], radius=5, fill=(68, 76, 88), outline=(108, 118, 132), width=1
            )
            d.text((kx + 16 if len(k) == 1 else kx + 8, ky + 9), k, fill=(240, 244, 250), font=_font(16, bold=True))
    d.rounded_rectangle([510, 214, 598, 258], radius=6, fill=(32, 152, 78), outline=(110, 232, 150), width=2)
    d.text((520, 228), "ON / OFF", fill=(248, 252, 248), font=_font(15, bold=True))
    # Bottom heavy-duty high-current terminal legends.
    d.line([28, 330, w - 28, 330], fill=(78, 86, 98), width=2)
    d.text((48, 342), "POWER", fill=(182, 192, 206), font=_font(14, bold=True))
    d.text((494, 340), "SENSE +/-", fill=(195, 205, 218), font=_font(14, bold=True))
    d.text((624, 340), "INPUT + (30A)", fill=(232, 76, 76), font=_font(15, bold=True))
    d.text((748, 340), "INPUT -", fill=(210, 218, 228), font=_font(15, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_awg_front() -> bytes:
    """Keysight 33500B / Rigol DG4000 dual-channel arbitrary waveform generator front panel."""
    w, h = 840, 400
    img = Image.new("RGB", (w, h), (38, 43, 50))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=16, fill=(46, 52, 60), outline=(92, 100, 114), width=4)
    d.rectangle([28, 20, 152, 25], fill=(214, 28, 48))
    d.text((28, 30), "KEYSIGHT", fill=(240, 244, 250), font=_font(22, bold=True))
    d.text((168, 32), "33522B   30 MHz Trueform Waveform Generator", fill=(186, 196, 210), font=_font(17, bold=True))
    # Dual-channel waveform preview TFT.
    d.rounded_rectangle([28, 66, 464, 286], radius=8, fill=(9, 15, 26), outline=(24, 28, 36), width=4)
    # CH1 Yellow Sine panel.
    d.rounded_rectangle([38, 76, 454, 174], radius=5, fill=(14, 24, 38), outline=(248, 208, 48), width=2)
    d.rectangle([40, 78, 120, 102], fill=(248, 208, 48))
    d.text((48, 81), "CH1 ON", fill=(14, 18, 24), font=_font(15, bold=True))
    d.text((132, 80), "SINE   1.00000 kHz   5.00 Vpp   HiZ", fill=(248, 215, 78), font=_font(15, bold=True, mono=True))
    pts_sin = [(52 + x, int(138 - 22 * math.sin(x * 0.055))) for x in range(0, 384, 3)]
    d.line(pts_sin, fill=(248, 208, 48), width=3)
    # CH2 Cyan Pulse panel.
    d.rounded_rectangle([38, 182, 454, 276], radius=5, fill=(14, 24, 38), outline=(52, 218, 248), width=2)
    d.rectangle([40, 184, 120, 208], fill=(52, 218, 248))
    d.text((48, 187), "CH2 ON", fill=(14, 18, 24), font=_font(15, bold=True))
    d.text((132, 186), "PULSE  100.00 kHz   3.30 Vpp   50%", fill=(95, 228, 248), font=_font(15, bold=True, mono=True))
    pts_sq = [(52 + x, 224 if (x // 32) % 2 == 0 else 260) for x in range(0, 384, 2)]
    d.line(pts_sq, fill=(52, 218, 248), width=3)
    # Waveform type softkey grid & right keypad.
    for i, wf in enumerate(("Sine", "Square", "Ramp", "Pulse", "Noise", "Arb")):
        wx = 488 + (i % 3) * 62
        wy = 76 + (i // 3) * 44
        d.rounded_rectangle([wx, wy, wx + 54, wy + 34], radius=5, fill=(66, 74, 88), outline=(108, 118, 134), width=1)
        d.text((wx + 8, wy + 9), wf, fill=(236, 242, 248), font=_font(13, bold=True))
    d.ellipse([696, 86, 792, 182], fill=(28, 32, 38), outline=(105, 114, 128), width=3)
    d.text((718, 192), "ADJUST", fill=(182, 192, 204), font=_font(13, bold=True))
    # Bottom BNC output callouts.
    d.line([28, 304, w - 28, 304], fill=(82, 90, 104), width=2)
    d.text((44, 316), "POWER", fill=(184, 194, 208), font=_font(14, bold=True))
    d.text((476, 316), "SYNC", fill=(190, 200, 214), font=_font(14, bold=True))
    d.text((572, 316), "CH1 OUT 50\u03a9", fill=(248, 208, 48), font=_font(14, bold=True))
    d.text((698, 316), "CH2 OUT 50\u03a9", fill=(52, 218, 248), font=_font(14, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_dmm_front() -> bytes:
    """Keysight 34461A / Fluke 8846A 6.5-Digit Benchtop Digital Multimeter front panel."""
    w, h = 860, 340
    img = Image.new("RGB", (w, h), (40, 45, 52))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=14, fill=(46, 52, 60), outline=(92, 100, 114), width=4)
    d.rectangle([28, 18, 146, 23], fill=(214, 28, 48))
    d.text((28, 28), "KEYSIGHT", fill=(240, 244, 250), font=_font(21, bold=True))
    d.text(
        (156, 30),
        "34461A   6\u00bd Digit Truevolt Digital Multimeter",
        fill=(186, 196, 210),
        font=_font(17, bold=True),
    )
    # High-contrast numeric Truevolt display.
    d.rounded_rectangle([28, 62, 502, 238], radius=8, fill=(9, 15, 25), outline=(22, 26, 34), width=4)
    d.rectangle([34, 68, 496, 94], fill=(20, 36, 56))
    d.text(
        (46, 73),
        "DC VOLTAGE   ·   AUTO 10V   ·   10 PLC   ·   10G\u03a9",
        fill=(168, 212, 244),
        font=_font(14, bold=True),
    )
    d.text((46, 114), "+12.00428", fill=(68, 232, 248), font=_font(56, bold=True, mono=True))
    d.text((394, 142), "V DC", fill=(180, 224, 242), font=_font(26, bold=True))
    # Mini bar-trend indicator below digits.
    d.rectangle([48, 198, 480, 212], fill=(20, 32, 48), outline=(48, 72, 98), width=1)
    d.rectangle([50, 200, 312, 210], fill=(56, 218, 148))
    d.text(
        (48, 216),
        "Min: +11.9981V    Avg: +12.0039V    Max: +12.0064V",
        fill=(142, 168, 196),
        font=_font(13, bold=True, mono=True),
    )
    # Measurement function keys below display.
    for i, (lbl, act) in enumerate(
        (
            ("DCV", True),
            ("ACV", False),
            ("DCI", False),
            ("\u03a9 2W", False),
            ("\u03a9 4W", False),
            ("Freq", False),
            ("Cont", False),
        )
    ):
        bx = 30 + i * 68
        d.rounded_rectangle(
            [bx, 254, bx + 60, 294],
            radius=5,
            fill=(32, 124, 172) if act else (66, 74, 86),
            outline=(112, 122, 136),
            width=1,
        )
        d.text((bx + 10, 266), lbl, fill=(244, 248, 252), font=_font(14, bold=True))
    # Right side safety jack labeling (4W Sense + Input HI/LO + 10A Fused).
    d.rounded_rectangle([526, 62, w - 26, 294], radius=8, fill=(56, 63, 74), outline=(92, 102, 116), width=2)
    d.text((544, 72), "4W SENSE", fill=(210, 218, 230), font=_font(14, bold=True))
    d.text((662, 72), "INPUT  HI", fill=(238, 86, 86), font=_font(14, bold=True))
    d.text((766, 72), "CAT II", fill=(246, 204, 52), font=_font(14, bold=True))
    d.text((548, 174), "SENSE LO", fill=(195, 204, 216), font=_font(14, bold=True))
    d.text((664, 174), "INPUT  LO", fill=(210, 218, 230), font=_font(14, bold=True))
    d.text((766, 174), "10A MAX", fill=(238, 86, 86), font=_font(14, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_fluke_dmm_front() -> bytes:
    """Fluke 87V industrial handheld True-RMS multimeter front face (LCD, keys, rotary dial & jacks)."""
    w, h = 420, 860
    img = Image.new("RGB", (w, h), (52, 56, 62))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14, 14, w - 14, h - 14], radius=28, fill=(58, 62, 70), outline=(36, 40, 46), width=4)
    # Iconic Fluke yellow brand badge top-left.
    d.rectangle([38, 38, 180, 74], fill=(245, 192, 18))
    d.text((48, 42), "FLUKE", fill=(22, 25, 28), font=_font(28, bold=True))
    d.text((196, 44), "87V", fill=(242, 246, 250), font=_font(26, bold=True))
    d.text((258, 50), "TRUE RMS", fill=(190, 198, 210), font=_font(15, bold=True))
    # Backlit LCD display.
    d.rounded_rectangle([38, 92, w - 38, 282], radius=10, fill=(142, 168, 148), outline=(28, 32, 36), width=5)
    d.text((54, 106), "AUTO   DC   TRUE RMS", fill=(24, 34, 28), font=_font(15, bold=True))
    d.text((54, 136), "12.04", fill=(18, 26, 22), font=_font(72, bold=True, mono=True))
    d.text((314, 166), "V", fill=(18, 26, 22), font=_font(36, bold=True))
    # Analog bar graph at bottom of LCD.
    for i in range(22):
        bx = 54 + i * 14
        bh = 16 if i % 5 == 0 else 10
        d.rectangle([bx, 252 - bh, bx + 8, 252], fill=(24, 34, 28) if i < 14 else (112, 134, 118))
    # 4 yellow/grey function softkeys.
    keys = (
        ("2nd", (245, 192, 18), (22, 24, 28)),
        ("MIN", (82, 88, 98), (238, 242, 246)),
        ("RNG", (82, 88, 98), (238, 242, 246)),
        ("HOLD", (82, 88, 98), (238, 242, 246)),
    )
    for i, (lbl, bg, fg) in enumerate(keys):
        kx = 42 + i * 86
        d.rounded_rectangle([kx, 304, kx + 76, 348], radius=8, fill=bg, outline=(32, 36, 42), width=2)
        d.text((kx + 12, 318), lbl, fill=fg, font=_font(16, bold=True))
    # Rotary dial scale legends around center (210, 504).
    cx, cy = 210, 504
    d.ellipse([cx - 108, cy - 108, cx + 108, cy + 108], fill=(46, 50, 56), outline=(88, 96, 108), width=3)
    dial_marks = (
        (-135, "OFF"),
        (-102, "V~"),
        (-68, "V="),
        (-34, "mV"),
        (0, "\u03a9"),
        (34, "mA"),
        (68, "\u03bcA"),
    )
    f_dial = _font(18, bold=True)
    for deg, lbl in dial_marks:
        rad = math.radians(deg - 90)
        tx = int(cx + 134 * math.cos(rad)) - 18
        ty = int(cy + 134 * math.sin(rad)) - 10
        d.text((tx, ty), lbl, fill=(245, 192, 18) if lbl == "V=" else (232, 236, 242), font=f_dial)
    # Bottom 4 safety terminal legends.
    d.line([36, 682, w - 36, 682], fill=(92, 98, 110), width=2)
    jacks = (("10A", (235, 78, 78)), ("mA", (235, 78, 78)), ("COM", (215, 222, 230)), ("V \u03a9", (235, 78, 78)))
    for i, (lbl, col) in enumerate(jacks):
        jx = 56 + i * 88
        d.text((jx, 700), lbl, fill=col, font=_font(18, bold=True))
    d.text((76, 804), "CAT IV 600V  ·  CAT III 1000V", fill=(245, 192, 18), font=_font(15, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_oscilloscope_screen() -> bytes:
    """4-channel mixed-signal oscilloscope display with graticule, real waveforms & CAN/SPI trigger bar."""
    w, h = 768, 480
    img = Image.new("RGB", (w, h), (7, 13, 24))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 34], fill=(16, 28, 48))
    d.rectangle([10, 6, 68, 28], fill=(24, 155, 82))
    d.text((19, 9), "RUN", fill=(245, 252, 248), font=_font(15, bold=True))
    d.text(
        (84, 9),
        "5.00 GS/s   100 us/div   Trig: CH1 Rising 1.65V   CAN-FD",
        fill=(195, 220, 242),
        font=_font(15, bold=True),
    )
    gx0, gy0, gx1, gy1 = 20, 44, w - 20, h - 46
    d.rectangle([gx0, gy0, gx1, gy1], fill=(9, 17, 30), outline=(42, 64, 92), width=2)
    for i in range(1, 10):
        x = gx0 + int((gx1 - gx0) * i / 10)
        d.line([x, gy0, x, gy1], fill=(24, 42, 66), width=1)
    for j in range(1, 8):
        y = gy0 + int((gy1 - gy0) * j / 8)
        d.line([gx0, y, gx1, y], fill=(24, 42, 66), width=1)
    cx, cy = (gx0 + gx1) // 2, (gy0 + gy1) // 2
    d.line([cx, gy0, cx, gy1], fill=(44, 72, 104), width=2)
    d.line([gx0, cy, gx1, cy], fill=(44, 72, 104), width=2)
    span = gx1 - gx0
    pts1 = [
        (gx0 + px, int(gy0 + 82 + 42 * math.sin(px * 0.055) * (0.75 + 0.25 * math.cos(px * 0.011))))
        for px in range(0, span, 2)
    ]
    d.line(pts1, fill=(252, 215, 48), width=3)
    pts2 = []
    for px in range(0, span, 3):
        bit = ((px // 18) * 7 + (px // 31)) % 3 == 0
        level = 175 if (120 < px < 610 and bit) else 212
        pts2.append((gx0 + px, gy0 + level))
    d.line(pts2, fill=(45, 224, 248), width=3)
    pts3 = [(gx0 + px, int(gy0 + 286 - 52 * math.exp(-px * 0.005) * math.sin(px * 0.08))) for px in range(0, span, 2)]
    d.line(pts3, fill=(238, 92, 196), width=3)
    pts4 = [(gx0 + px, gy0 + (342 if (px // 24) % 2 == 0 else 372)) for px in range(0, span, 2)]
    d.line(pts4, fill=(58, 232, 128), width=3)
    d.rectangle([0, h - 38, w, h], fill=(14, 24, 42))
    badges = (
        ("CH1 2.0V", (252, 215, 48)),
        ("CH2 1.0V", (45, 224, 248)),
        ("CH3 500mV", (238, 92, 196)),
        ("CH4 3.3V", (58, 232, 128)),
    )
    for i, (txt, col) in enumerate(badges):
        bx = 16 + i * 144
        d.rounded_rectangle([bx, h - 32, bx + 130, h - 6], radius=4, fill=(22, 34, 54), outline=col, width=2)
        d.text((bx + 12, h - 28), txt, fill=col, font=_font(15, bold=True))
    d.text((598, h - 28), "f=500.0 kHz", fill=(210, 228, 245), font=_font(15, bold=True, mono=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_rf_spectrum_screen() -> bytes:
    """Rohde & Schwarz FSVA / Keysight EXA RF spectrum analyzer screen with carrier peak & markers."""
    w, h = 768, 480
    img = Image.new("RGB", (w, h), (7, 12, 22))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 36], fill=(18, 30, 52))
    d.text(
        (14, 9),
        "SPECTRUM  ·  Ref 0.0 dBm   Att 10 dB   RBW 100 kHz   VBW 300 kHz",
        fill=(198, 222, 246),
        font=_font(15, bold=True),
    )
    gx0, gy0, gx1, gy1 = 46, 48, w - 20, h - 54
    d.rectangle([gx0, gy0, gx1, gy1], fill=(10, 16, 28), outline=(44, 68, 98), width=2)
    for i in range(1, 10):
        x = gx0 + int((gx1 - gx0) * i / 10)
        d.line([x, gy0, x, gy1], fill=(24, 42, 66), width=1)
    for j in range(1, 8):
        y = gy0 + int((gy1 - gy0) * j / 8)
        d.line([gx0, y, gx1, y], fill=(24, 42, 66), width=1)
        d.text((6, y - 7), f"-{j * 10}", fill=(125, 148, 175), font=_font(12, bold=True, mono=True))
    span = gx1 - gx0
    pts_live = []
    pts_max = []
    for px in range(0, span, 2):
        # Noise floor + 2.442 GHz carrier + modulated skirts + harmonic spur.
        u = px / span
        carrier = 278 * math.exp(-(((u - 0.44) / 0.022) ** 2))
        side_l = 122 * math.exp(-(((u - 0.37) / 0.032) ** 2))
        side_r = 122 * math.exp(-(((u - 0.51) / 0.032) ** 2))
        spur = 165 * math.exp(-(((u - 0.76) / 0.015) ** 2))
        ripple = 10 * math.sin(px * 0.43) + 6 * math.cos(px * 0.91)
        y_val = int(gy1 - 44 - carrier - side_l - side_r - spur - ripple)
        y_val = max(gy0 + 8, min(gy1 - 8, y_val))
        pts_live.append((gx0 + px, y_val))
        pts_max.append((gx0 + px, max(gy0 + 6, y_val - 14)))
    d.line(pts_max, fill=(45, 198, 245), width=2)
    d.line(pts_live, fill=(252, 212, 42), width=3)
    # Red marker diamond on main peak.
    mx = gx0 + int(span * 0.44)
    my = gy1 - 44 - 278
    d.polygon([(mx, my - 10), (mx + 9, my), (mx, my + 10), (mx - 9, my)], fill=(238, 62, 74))
    d.rounded_rectangle([w - 280, 58, w - 32, 118], radius=6, fill=(18, 28, 46), outline=(238, 62, 74), width=2)
    d.text((w - 268, 66), "M1  2.44200 GHz", fill=(252, 212, 42), font=_font(16, bold=True, mono=True))
    d.text((w - 268, 90), "    -11.82 dBm", fill=(236, 244, 250), font=_font(16, bold=True, mono=True))
    d.rectangle([0, h - 42, w, h], fill=(14, 24, 42))
    d.text((22, h - 31), "Start 2.350 GHz", fill=(180, 206, 232), font=_font(15, bold=True, mono=True))
    d.text((284, h - 31), "CF 2.450 GHz  ·  Span 200 MHz", fill=(242, 248, 252), font=_font(15, bold=True, mono=True))
    d.text((612, h - 31), "Stop 2.550 GHz", fill=(180, 206, 232), font=_font(15, bold=True, mono=True))
    return _to_png(img)


# --- Embedded boards, ECUs, Network, Soldering, HIL, Climatic, UPS, Furniture decals -----------------------


@functools.lru_cache(maxsize=32)
def tex_raspberry_pi_pcb() -> bytes:
    """Raspberry Pi 5/4B high-density green PCB top surface with copper traces, GPIO labels & silkscreen."""
    w, h = 640, 420
    img = Image.new("RGB", (w, h), (22, 118, 56))
    d = ImageDraw.Draw(img)
    for x in range(18, w - 18, 24):
        d.line([x, 18, x, h - 18], fill=(28, 134, 65), width=2)
    for y in range(24, h - 24, 26):
        d.line([18, y, w - 18, y], fill=(26, 128, 62), width=2)
    for i in range(10):
        d.line([160 + i * 12, 92, 260 + i * 12, 195], fill=(42, 162, 82), width=3)
        d.line([290 + i * 10, 215, 420 + i * 10, 310], fill=(42, 162, 82), width=3)
    for mx, my in ((38, 38), (38, h - 38), (455, 38), (455, h - 38)):
        d.ellipse([mx - 22, my - 22, mx + 22, my + 22], fill=(218, 178, 62), outline=(168, 130, 35), width=3)
        d.ellipse([mx - 12, my - 12, mx + 12, my + 12], fill=(16, 20, 24))
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=24, outline=(225, 242, 232), width=3)
    d.text((88, 32), "GPIO 40-PIN  J8", fill=(235, 246, 238), font=_font(16, bold=True))
    d.text((70, 276), "Raspberry Pi 5", fill=(242, 250, 244), font=_font(24, bold=True))
    d.text((70, 306), "8GB  LPDDR4X   PCIe 2.0", fill=(208, 234, 218), font=_font(15, bold=True))
    d.text((84, 382), "PWR IN 5V   HDMI0   HDMI1   CAM/DISP", fill=(228, 244, 234), font=_font(14, bold=True))
    for px in range(120, 420, 34):
        d.ellipse([px, 344, px + 10, 354], fill=(224, 186, 72))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_stm32_nucleo_pcb() -> bytes:
    """STM32 Nucleo-144 crisp white solder-mask evaluation board silkscreen & trace pattern."""
    w, h = 480, 760
    img = Image.new("RGB", (w, h), (238, 241, 244))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=16, outline=(188, 194, 202), width=3)
    # Subtle light-grey PCB trace routing under white solder mask.
    for i in range(14):
        d.line([62 + i * 26, 210, 62 + i * 26, 680], fill=(222, 226, 232), width=2)
    # Snap-off ST-LINK/V3E upper section with perforation line.
    d.line([16, 202, w - 16, 202], fill=(135, 142, 152), width=3)
    for px in range(32, w - 24, 24):
        d.ellipse([px, 197, px + 10, 207], fill=(170, 176, 184))
    d.rectangle([28, 28, 108, 72], fill=(16, 68, 152))
    d.text((40, 36), "ST", fill=(248, 250, 252), font=_font(28, bold=True))
    d.text((126, 36), "ST-LINK/V3E", fill=(32, 42, 56), font=_font(24, bold=True))
    d.text((126, 68), "MB1364  SWD / VCP", fill=(95, 104, 118), font=_font(15, bold=True))
    # Main MCU section silkscreen (centered cleanly in open white PCB zone between Morpho headers).
    d.text((132, 218), "NUCLEO-H743ZI2", fill=(22, 54, 128), font=_font(22, bold=True))
    d.text((146, 246), "STM32H7  ·  480MHz", fill=(82, 92, 106), font=_font(15, bold=True))
    # Header pin legends left & right.
    d.text((18, 286), "CN11", fill=(62, 70, 82), font=_font(13, bold=True))
    d.text((w - 58, 286), "CN12", fill=(62, 70, 82), font=_font(13, bold=True))
    d.text((120, 566), "B1 USER", fill=(24, 98, 198), font=_font(14, bold=True))
    d.text((280, 566), "B2 RESET", fill=(48, 54, 64), font=_font(14, bold=True))
    d.text((126, 718), "ETH  ·  USB OTG  ·  CAN-FD", fill=(58, 66, 78), font=_font(15, bold=True))
    # Corner mounting hole rings.
    for mx, my in ((34, 224), (w - 34, 224), (34, h - 34), (w - 34, h - 34)):
        d.ellipse([mx - 14, my - 14, mx + 14, my + 14], fill=(215, 178, 66), outline=(160, 126, 35), width=2)
        d.ellipse([mx - 7, my - 7, mx + 7, my + 7], fill=(26, 30, 36))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_eval_board_pcb() -> bytes:
    """Automotive SoC / ECU evaluation board (NXP S32G / AURIX style) green multi-layer PCB texture."""
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (16, 98, 52))
    d = ImageDraw.Draw(img)
    for x in range(20, w - 20, 22):
        d.line([x, 20, x, h - 20], fill=(22, 114, 62), width=2)
    for y in range(20, h - 20, 22):
        d.line([20, y, w - 20, y], fill=(20, 108, 58), width=2)
    for i in range(12):
        d.line([110 + i * 11, 140, 240 + i * 11, 270], fill=(38, 154, 86), width=3)
    d.rounded_rectangle([10, 10, w - 10, h - 10], radius=18, outline=(228, 242, 234), width=3)
    d.text(
        (34, 24),
        "AUTO-SOC-EVB  Rev 3.2   ·   JTAG / TRACE / CAN-FD / 1000BASE-T1",
        fill=(238, 248, 242),
        font=_font(15, bold=True),
    )
    d.text(
        (34, 434),
        "ETH0     USB-C     CAN-FD 1/2       RF SMA     12V IN",
        fill=(238, 248, 242),
        font=_font(16, bold=True),
    )
    for mx, my in ((34, 58), (w - 34, 58), (34, h - 54), (w - 34, h - 54)):
        d.ellipse([mx - 15, my - 15, mx + 15, my + 15], fill=(218, 178, 62), outline=(156, 122, 32), width=2)
        d.ellipse([mx - 8, my - 8, mx + 8, my + 8], fill=(18, 22, 26))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_eval_board_oled() -> bytes:
    """High-contrast diagnostic OLED screen for embedded dev kit."""
    w, h = 320, 200
    img = Image.new("RGB", (w, h), (6, 12, 22))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 34], fill=(18, 52, 86))
    d.text((14, 8), "SOC-EVB  AUTOSAR OS", fill=(115, 228, 250), font=_font(16, bold=True))
    d.text((14, 48), "CPU: 400 MHz  38.4C", fill=(72, 238, 145), font=_font(18, bold=True, mono=True))
    d.text((14, 84), "CAN0: 5Mbps   OK", fill=(250, 208, 65), font=_font(18, bold=True, mono=True))
    d.text((14, 120), "ETH0: 1000T1  UP", fill=(78, 218, 248), font=_font(18, bold=True, mono=True))
    d.text((14, 156), "VDD: 3.30V   1.12A", fill=(215, 230, 242), font=_font(17, bold=True, mono=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_ecu_dut_top() -> bytes:
    """Die-cast automotive ECU / ADAS domain controller top nameplate & data-matrix label."""
    w, h = 640, 420
    img = Image.new("RGB", (w, h), (168, 174, 182))
    d = ImageDraw.Draw(img)
    # Brushed cast-aluminum subtle texture lines.
    for y in range(0, h, 6):
        d.line([0, y, w, y], fill=(160, 166, 174), width=2)
    # Industrial white/dark asset nameplate sticker centered on lid.
    d.rounded_rectangle([54, 46, w - 54, h - 46], radius=14, fill=(242, 244, 246), outline=(56, 62, 72), width=4)
    d.rectangle([58, 50, w - 58, 114], fill=(28, 42, 64))
    d.text((80, 66), "AUTOMOTIVE ECU  ·  ADAS DOMAIN CTRL", fill=(245, 248, 252), font=_font(22, bold=True))
    d.text((80, 134), "P/N: 0 261 S20 842   ·   HW Rev 3.2", fill=(32, 38, 46), font=_font(20, bold=True, mono=True))
    d.text((80, 168), "12V DC  ·  4x CAN-FD  ·  1000BASE-T1", fill=(62, 70, 82), font=_font(18, bold=True))
    d.text((80, 200), "SW: AUTOSAR R22-11   DUT-BENCH", fill=(62, 70, 82), font=_font(17, bold=False))
    # Crisp 2D DataMatrix barcode block bottom-right.
    bx0, by0 = 438, 224
    d.rectangle([bx0, by0, bx0 + 112, by0 + 112], fill=(252, 252, 252), outline=(28, 32, 38), width=3)
    for r in range(9):
        for c in range(9):
            if r == 0 or c == 0 or ((r * 7 + c * 13 + r * c) % 3 == 0):
                d.rectangle(
                    [bx0 + 8 + c * 10, by0 + 8 + r * 10, bx0 + 16 + c * 10, by0 + 16 + r * 10], fill=(20, 24, 28)
                )
    # Linear barcode bottom-left.
    for i in range(44):
        bw = 4 if (i * 5 + 3) % 3 == 0 else 2
        if (i * 7 + 1) % 2 == 0:
            d.rectangle([80 + i * 7, 256, 80 + i * 7 + bw, 316], fill=(22, 26, 30))
    d.text((80, 324), "S/N: ECU-2026-0482-A    CE  ESD", fill=(45, 52, 62), font=_font(16, bold=True, mono=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_switch_front() -> bytes:
    """Cisco Catalyst / Netgear 1U 24-Port Managed Ethernet + 4xSFP+ Switch faceplate."""
    w, h = 960, 108
    img = Image.new("RGB", (w, h), (96, 106, 118))
    d = ImageDraw.Draw(img)
    d.rectangle([3, 3, w - 4, h - 4], outline=(142, 152, 166), width=3)
    d.rectangle([10, 10, 134, 96], fill=(18, 30, 48), outline=(56, 98, 146), width=2)
    d.text((18, 18), "CATALYST", fill=(92, 212, 252), font=_font(18, bold=True))
    d.text((18, 44), "9200L · 24G", fill=(230, 238, 246), font=_font(13, bold=True))
    d.text((18, 68), "SYST  PoE  OK", fill=(82, 238, 142), font=_font(12, bold=True))
    # Dark recessed port-bank bezels & crisp numbering above/below the 3D RJ45 cages.
    d.rounded_rectangle([146, 22, 396, 86], radius=4, fill=(32, 38, 46))
    d.rounded_rectangle([404, 22, 654, 86], radius=4, fill=(32, 38, 46))
    d.rounded_rectangle([668, 24, 864, 84], radius=4, fill=(28, 36, 46))
    f_num = _font(12, bold=True)
    for bank in range(2):
        for col in range(6):
            px = 166 + bank * 250 + col * 38
            d.text((px, 6), f"{bank * 12 + col * 2 + 1}", fill=(242, 248, 252), font=f_num)
            d.text((px, 88), f"{bank * 12 + col * 2 + 2}", fill=(242, 248, 252), font=f_num)
    d.text((674, 6), "SFP+ 10G   25    26    27    28", fill=(224, 244, 255), font=_font(12, bold=True))
    d.text((886, 6), "CON", fill=(242, 248, 252), font=_font(12, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_soldering_front() -> bytes:
    """Weller WT / Quick ESD digital dual soldering & hot-air rework station faceplate."""
    w, h = 640, 400
    img = Image.new("RGB", (w, h), (26, 52, 74))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=16, fill=(22, 46, 68), outline=(72, 108, 138), width=4)
    d.text((34, 22), "Weller", fill=(242, 248, 252), font=_font(30, bold=True))
    d.text((168, 30), "WT2M  ESD Digital Rework Station", fill=(168, 206, 232), font=_font(18, bold=True))
    # Dual glowing red/amber 7-segment temperature windows.
    d.rounded_rectangle([32, 74, 308, 214], radius=10, fill=(14, 18, 24), outline=(64, 86, 108), width=3)
    d.text((48, 84), "CH1 SOLDER IRON", fill=(162, 184, 204), font=_font(15, bold=True))
    d.text((52, 114), "350\u00b0C", fill=(252, 178, 42), font=_font(56, bold=True, mono=True))
    d.rounded_rectangle([332, 74, w - 32, 214], radius=10, fill=(14, 18, 24), outline=(64, 86, 108), width=3)
    d.text((348, 84), "CH2 HOT AIR · 65%", fill=(162, 184, 204), font=_font(15, bold=True))
    d.text((352, 114), "380\u00b0C", fill=(245, 78, 72), font=_font(56, bold=True, mono=True))
    # Preset temperature buttons.
    for i, lbl in enumerate(("250\u00b0", "350\u00b0", "400\u00b0", "AIR -", "AIR +")):
        bx = 38 + i * 114
        d.rounded_rectangle([bx, 234, bx + 98, 276], radius=6, fill=(44, 72, 98), outline=(92, 128, 158), width=2)
        d.text((bx + 22, 246), lbl, fill=(238, 246, 252), font=_font(17, bold=True))
    d.text((40, 344), "ESD SAFE  ·  CH1 IRON", fill=(180, 212, 234), font=_font(16, bold=True))
    d.text((386, 344), "CH2 HOT AIR", fill=(180, 212, 234), font=_font(16, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_hil_screen() -> bytes:
    """dSPACE SCALEXIO / NI HIL real-time simulator live telemetry monitor screen."""
    w, h = 768, 420
    img = Image.new("RGB", (w, h), (10, 18, 30))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 34], fill=(20, 40, 66))
    d.text(
        (16, 8),
        "HIL REAL-TIME SIMULATOR  ·  SCALEXIO ControlDesk  ·  1.0 kHz",
        fill=(165, 216, 248),
        font=_font(15, bold=True),
    )
    # KPI cards across top.
    cards = (
        ("ECU STATE", "RUN · OK", (52, 228, 128)),
        ("VEH SPEED", "84.2 km/h", (62, 218, 248)),
        ("HV BATT", "398.4 V", (252, 206, 48)),
        ("TESTS PASS", "142 / 142", (52, 228, 128)),
    )
    for i, (lbl, val, col) in enumerate(cards):
        cx = 16 + i * 186
        d.rounded_rectangle([cx, 46, cx + 174, 126], radius=8, fill=(16, 28, 46), outline=(38, 62, 92), width=2)
        d.text((cx + 12, 56), lbl, fill=(142, 174, 206), font=_font(13, bold=True))
        d.text((cx + 12, 82), val, fill=col, font=_font(24, bold=True, mono=True))
    # Live closed-loop simulation plot.
    d.rounded_rectangle([16, 140, w - 16, h - 16], radius=8, fill=(12, 20, 34), outline=(38, 62, 92), width=2)
    d.text(
        (32, 152),
        "Closed-Loop Powertrain Torque & Motor Current Trace",
        fill=(192, 216, 240),
        font=_font(15, bold=True),
    )
    p1 = [(34 + x, int(268 - 54 * math.sin(x * 0.018) - 18 * math.cos(x * 0.06))) for x in range(0, 700, 4)]
    p2 = [(34 + x, int(312 - 36 * math.cos(x * 0.014))) for x in range(0, 700, 4)]
    d.line(p1, fill=(58, 222, 248), width=3)
    d.line(p2, fill=(65, 232, 138), width=3)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_hil_patch_panel() -> bytes:
    """HIL Fault-Injection Unit (FIU) & ECU Breakout Patch Panel silkscreen."""
    w, h = 768, 320
    img = Image.new("RGB", (w, h), (22, 42, 68))
    d = ImageDraw.Draw(img)
    d.rectangle([6, 6, w - 7, h - 7], outline=(82, 118, 158), width=3)
    d.rectangle([10, 10, w - 10, 52], fill=(14, 26, 44))
    d.text(
        (24, 20),
        "FIU / ECU BREAKOUT PATCH PANEL  ·  CAN1-4 · LIN · FlexRay · KL30/KL15",
        fill=(215, 232, 248),
        font=_font(16, bold=True),
    )
    rows = ("CAN-FD / ETH", "ANALOG I/O", "KL30 / KL15 / GND")
    for r, title in enumerate(rows):
        ry = 70 + r * 80
        d.text((24, ry), title, fill=(148, 198, 236), font=_font(15, bold=True))
        d.line([24, ry + 22, w - 24, ry + 22], fill=(56, 86, 122), width=2)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_thermal_controller() -> bytes:
    """ESPEC / Weiss Technik environmental chamber PID touchscreen controller."""
    w, h = 480, 280
    img = Image.new("RGB", (w, h), (14, 22, 34))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 38], fill=(24, 52, 86))
    d.text((14, 10), "CLIMATIC CHAMBER  ·  PROGRAM RUN", fill=(195, 228, 250), font=_font(16, bold=True))
    d.rounded_rectangle([16, 52, 234, 152], radius=8, fill=(10, 18, 30), outline=(52, 212, 245), width=2)
    d.text((28, 60), "TEMP PV (SP -40.0)", fill=(142, 188, 222), font=_font(14, bold=True))
    d.text((28, 86), "-40.0\u00b0C", fill=(62, 224, 250), font=_font(42, bold=True, mono=True))
    d.rounded_rectangle([248, 52, w - 16, 152], radius=8, fill=(10, 18, 30), outline=(56, 224, 134), width=2)
    d.text((260, 60), "HUMIDITY (SP 65%)", fill=(142, 206, 174), font=_font(14, bold=True))
    d.text((260, 86), "65.0%", fill=(64, 234, 138), font=_font(42, bold=True, mono=True))
    # Mini ramp curve graph.
    d.rounded_rectangle([16, 166, w - 16, h - 14], radius=8, fill=(10, 16, 26), outline=(42, 64, 92), width=2)
    pts = [(32, 246), (110, 246), (176, 186), (312, 186), (378, 246), (448, 246)]
    d.line(pts, fill=(252, 196, 48), width=4)
    d.text(
        (34, 174),
        "CYCLE 04/20  -40\u00b0C \u2194 +85\u00b0C  SOAK 2h",
        fill=(186, 206, 228),
        font=_font(14, bold=True),
    )
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_ups_lcd() -> bytes:
    """APC Smart-UPS 3000VA backlit blue LCD telemetry screen."""
    w, h = 420, 240
    img = Image.new("RGB", (w, h), (16, 62, 118))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, w - 5, h - 5], outline=(112, 186, 242), width=3)
    d.rectangle([8, 8, w - 8, 48], fill=(12, 46, 92))
    d.text((18, 16), "ONLINE  ·  Smart-UPS 3000VA", fill=(224, 242, 255), font=_font(19, bold=True))
    d.text((20, 62), "OUT: 230V  50.0Hz", fill=(238, 248, 255), font=_font(24, bold=True, mono=True))
    d.text((20, 102), "LOAD: 48%  1.44kW", fill=(135, 246, 185), font=_font(24, bold=True, mono=True))
    d.text((20, 142), "BATT: 100%  42min", fill=(252, 226, 95), font=_font(24, bold=True, mono=True))
    # Load bar graph.
    d.rectangle([20, 186, w - 20, 214], fill=(10, 38, 76), outline=(118, 188, 242), width=2)
    for i in range(6):
        d.rectangle([26 + i * 32, 192, 52 + i * 32, 208], fill=(92, 240, 162))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_safety_placard() -> bytes:
    """Flammable Safety Cabinet red-and-white industrial hazard warning placard."""
    w, h = 512, 220
    img = Image.new("RGB", (w, h), (242, 244, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, w - 8, h - 8], fill=(246, 246, 246), outline=(196, 20, 28), width=10)
    d.rectangle([20, 20, w - 20, 118], fill=(196, 20, 28))
    d.text((88, 36), "FLAMMABLE", fill=(252, 252, 252), font=_font(54, bold=True))
    d.text((76, 138), "KEEP FIRE AWAY", fill=(196, 20, 28), font=_font(40, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_fume_hood_monitor() -> bytes:
    """Laboratory fume hood digital face-velocity airflow safety monitor."""
    w, h = 420, 160
    img = Image.new("RGB", (w, h), (24, 30, 38))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, w - 6, h - 6], radius=10, fill=(28, 36, 46), outline=(74, 88, 104), width=3)
    d.text((22, 18), "AIRFLOW MONITOR · SASH OK", fill=(176, 202, 226), font=_font(17, bold=True))
    d.rounded_rectangle([22, 52, 258, 136], radius=6, fill=(10, 18, 26), outline=(48, 72, 92), width=2)
    d.text((34, 68), "0.52 m/s", fill=(62, 236, 134), font=_font(40, bold=True, mono=True))
    d.ellipse([292, 60, 344, 112], fill=(42, 218, 112), outline=(140, 245, 180), width=3)
    d.text((294, 118), "SAFE", fill=(92, 236, 148), font=_font(16, bold=True))
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_monitor_screen() -> bytes:
    """Realistic dark automotive embedded IDE & CANoe/telemetry dashboard screen for lab monitors."""
    w, h = 768, 440
    img = Image.new("RGB", (w, h), (13, 20, 32))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 28], fill=(20, 32, 50))
    d.text(
        (14, 6),
        "TRACE32 / CANoe  ·  ECU Bench Telemetry  ·  1000BASE-T1",
        fill=(165, 205, 238),
        font=_font(14, bold=True),
    )
    d.rectangle([0, 28, 152, h], fill=(16, 25, 40))
    for i, item in enumerate(
        ("ECU_Main.elf", "CAN_FD_Bus1", "Eth_SOMEIP", "PowerRail_12V", "Watch_Vars", "Trace_Buffer")
    ):
        d.text((14, 46 + i * 28), item, fill=(140, 178, 212) if i != 1 else (95, 225, 245), font=_font(13, bold=True))
    d.rounded_rectangle([166, 40, w - 14, 236], radius=6, fill=(10, 17, 29), outline=(34, 54, 82), width=2)
    d.text((180, 48), "Live Bus Load & Voltage Rail", fill=(185, 212, 238), font=_font(14, bold=True))
    pts_a = [(180 + x, int(146 - 44 * math.sin(x * 0.028) - 14 * math.cos(x * 0.08))) for x in range(0, 550, 4)]
    pts_b = [(180 + x, int(176 - 24 * math.cos(x * 0.022))) for x in range(0, 550, 4)]
    d.line(pts_a, fill=(52, 212, 245), width=3)
    d.line(pts_b, fill=(58, 224, 138), width=3)
    d.rounded_rectangle([166, 250, w - 14, h - 14], radius=6, fill=(10, 17, 29), outline=(34, 54, 82), width=2)
    rows = (
        ("0.0124s  CAN1  0x2F4  Rx  8   4A 12 00 F8 7C 01 9B 44  OK", (110, 228, 158)),
        ("0.0148s  CAN1  0x1A0  Tx  8   01 80 3F 00 00 12 A0 0E  OK", (110, 205, 245)),
        ("0.0172s  ETH1  SOMEIP 64  Svc 0x1042  Method 0x0012   200", (245, 205, 85)),
        ("0.0196s  DBG0  Core0  RUN  PC=0x8004A210  Temp=41.2C  OK", (185, 205, 225)),
        ("0.0220s  PSU1  CH1=+13.80V  I=2.44A  P=33.7W  CV      OK", (110, 228, 158)),
    )
    f_log = _font(13, bold=True, mono=True)
    for i, (line, col) in enumerate(rows):
        d.text((180, 266 + i * 28), line, fill=col, font=f_log)
    return _to_png(img)


@functools.lru_cache(maxsize=32)
def tex_workstation_front() -> bytes:
    """Modern Dell Precision / Lenovo ThinkStation style honeycomb-mesh front bezel."""
    w, h = 256, 512
    img = Image.new("RGB", (w, h), (22, 25, 30))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, w - 6, h - 6], radius=12, fill=(26, 30, 36), outline=(52, 58, 68), width=3)
    d.rectangle([18, 22, w - 18, 108], fill=(34, 39, 48), outline=(58, 66, 78), width=2)
    d.ellipse([36, 48, 64, 76], fill=(22, 26, 32), outline=(65, 205, 245), width=3)
    for ux in (98, 132, 166):
        d.rectangle([ux, 54, ux + 22, 68], fill=(12, 15, 20), outline=(92, 102, 118), width=2)
    d.rounded_rectangle([202, 56, 222, 66], radius=4, fill=(12, 15, 20), outline=(120, 132, 148), width=2)
    d.rounded_rectangle([18, 128, w - 18, h - 22], radius=8, fill=(16, 19, 24), outline=(44, 50, 60), width=2)
    for y in range(142, h - 32, 12):
        d.line([28, y, w - 28, y], fill=(36, 42, 52), width=4)
    for x in range(38, w - 34, 24):
        d.line([x, 134, x, h - 28], fill=(20, 24, 30), width=3)
    return _to_png(img)
