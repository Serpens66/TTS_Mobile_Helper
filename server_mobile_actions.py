import socket
import json
import time
import math
import logging
import uuid
import qrcode
import sys
import locale
import argparse
from ipaddress import IPv4Address, ip_address
from os import environ
from pathlib import Path
from flask import Flask, render_template_string, request, send_from_directory, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room
import engineio.async_drivers.threading  # needed by PyInstaller for async_mode="threading"
import struct
import threading
import re
from urllib.parse import urlparse

from tts_api_chatgpt import ExternalEditorApi as ExternalEditorApi_chatgpt

TTS_IMAGE_CACHE_DIRS = [
    Path.home() / "Documents" / "My Games" / "Tabletop Simulator" / "Mods" / "Images",
]


app = Flask(__name__)
socketio = SocketIO(app,cors_allowed_origins=None,async_mode="threading",allow_upgrades=False)


@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' http: https: data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

tts_api_chatgpt = None
TTS_ADAPTER_LOCK = threading.Lock()
TTS_API_DEBUG_INCOMING = False
TTS_API_DEBUG_OUTGOING = False
LAN_IP_OVERRIDE = None


def parse_lan_ip(value):
    try:
        address = IPv4Address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a valid IPv4 address") from exc
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_reserved:
        raise argparse.ArgumentTypeError("expected the IPv4 address of a LAN interface")
    return str(address)


def parse_start_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="TTS Mobile Companion Server"
    )
    parser.add_argument(
        "--lan-ip",
        type=parse_lan_ip,
        metavar="IPv4",
        help="Use this LAN address in phone links instead of auto-detecting it.",
    )
    parser.add_argument(
        "--debug-tts-api",
        action="store_true",
        help="Aktiviert Debug-Ausgaben fuer eingehende und ausgehende TTS External API Nachrichten.",
    )
    parser.add_argument(
        "--debug-tts-incoming",
        action="store_true",
        help="Aktiviert Debug-Ausgaben fuer eingehende TTS External API Nachrichten.",
    )
    parser.add_argument(
        "--debug-tts-outgoing",
        action="store_true",
        help="Aktiviert Debug-Ausgaben fuer ausgehende TTS External API Nachrichten.",
    )
    return parser.parse_args(argv)


def apply_start_arguments(args):
    global TTS_API_DEBUG_INCOMING, TTS_API_DEBUG_OUTGOING, LAN_IP_OVERRIDE
    LAN_IP_OVERRIDE = args.lan_ip
    TTS_API_DEBUG_INCOMING = bool(args.debug_tts_api or args.debug_tts_incoming)
    TTS_API_DEBUG_OUTGOING = bool(args.debug_tts_api or args.debug_tts_outgoing)


def get_tts_api_chatgpt():
    global tts_api_chatgpt
    with TTS_ADAPTER_LOCK:
        if tts_api_chatgpt is None:
            tts_api_chatgpt = ExternalEditorApi_chatgpt(
                debug_incoming=TTS_API_DEBUG_INCOMING,
                debug_outgoing=TTS_API_DEBUG_OUTGOING,
                collect_events=False,
            )
        return tts_api_chatgpt

# Speicher fuer die aktuellen Handkarten der Spieler
# Struktur: {"Red": [{"guid": "123456", "name": "Holz", "image": "url"}], "Blue": ...}
LANGUAGE_FILES = {
    "de": "german.json",
    "en": "english.json",
    "es": "spanish.json",
    "fr": "french.json",
    "it": "italian.json",
    "pt": "portuguese.json",
    "nl": "dutch.json",
    "pl": "polish.json",
    "ru": "russian.json",
    "zh": "chinese_simplified.json",
    "ja": "japanese.json",
    "ko": "korean.json",
}
LANGUAGE_PREFIXES = tuple(LANGUAGE_FILES.keys())
DEFAULT_LANGUAGE = "en"
LOCALIZATIONS = {}


def app_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_base_dir():
    return Path(getattr(sys, "_MEIPASS", app_base_dir())).resolve()


def resource_file_path(*parts):
    external_path = app_base_dir().joinpath(*parts)
    if external_path.exists():
        return external_path
    bundled_path = bundled_base_dir().joinpath(*parts)
    if bundled_path.exists():
        return bundled_path
    return external_path


def normalize_language_tag(tag):
    if not tag:
        return None
    tag = str(tag).strip().lower().replace("_", "-")
    if not tag:
        return None
    for language in LANGUAGE_PREFIXES:
        if tag.startswith(language):
            return language
    return None


def parse_accept_language(value):
    languages = []
    for part in str(value or "").split(","):
        tag = part.split(";", 1)[0].strip()
        language = normalize_language_tag(tag)
        if language and language not in languages:
            languages.append(language)
    return languages


def pc_language():
    candidates = []
    try:
        language, encoding = locale.getlocale()
        candidates.append(language)
        candidates.append(encoding)
    except Exception:
        pass
    try:
        candidates.append(locale.getencoding())
    except Exception:
        pass
    for env_name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        candidates.append(environ.get(env_name))
    for candidate in candidates:
        language = normalize_language_tag(candidate)
        if language:
            return language
    return DEFAULT_LANGUAGE


PC_LANGUAGE = pc_language()


def load_localization_file(language, filename):
    path = resource_file_path("localization", filename)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
    except FileNotFoundError:
        print(f"[WARNUNG] Localization-Datei fehlt: {path}")
    except Exception as exc:
        print(f"[WARNUNG] Localization-Datei konnte nicht geladen werden ({language}): {exc}")
    return {}


def load_localizations():
    return {
        language: load_localization_file(language, filename)
        for language, filename in LANGUAGE_FILES.items()
    }


def refresh_localizations():
    global LOCALIZATIONS
    LOCALIZATIONS = load_localizations()


refresh_localizations()


def resolve_language(candidates=None):
    for candidate in candidates or []:
        if isinstance(candidate, (list, tuple)):
            nested = resolve_language(candidate)
            if nested:
                return nested
            continue
        language = normalize_language_tag(candidate)
        if language in LANGUAGE_FILES:
            return language
    if PC_LANGUAGE in LANGUAGE_FILES:
        return PC_LANGUAGE
    return DEFAULT_LANGUAGE


def request_language():
    explicit = request.args.get("lang")
    accept_languages = parse_accept_language(request.headers.get("Accept-Language", ""))
    return resolve_language([explicit, accept_languages, PC_LANGUAGE])


def client_language_from_data(data):
    if not isinstance(data, dict):
        return resolve_language([PC_LANGUAGE])
    return resolve_language([
        data.get("language"),
        data.get("languages"),
        PC_LANGUAGE,
    ])


def client_language_from_sid(sid):
    session = client_sessions.get(sid) or {}
    return resolve_language([session.get("language"), PC_LANGUAGE])


def translate(key, language=None, params=None):
    language = resolve_language([language, PC_LANGUAGE])
    params = params or {}
    text = (
        LOCALIZATIONS.get(language, {}).get(key) or
        LOCALIZATIONS.get(DEFAULT_LANGUAGE, {}).get(key) or
        LOCALIZATIONS.get("de", {}).get(key) or
        key
    )
    try:
        return text.format(**params)
    except Exception:
        return text


def localized_payload(key, language=None, params=None, field="message", **extra):
    payload = {
        field: translate(key, language, params),
        f"{field}_key": key,
        f"{field}_params": params or {},
    }
    payload.update(extra)
    return payload


def client_i18n(language):
    language = resolve_language([language, PC_LANGUAGE])
    merged = {}
    merged.update(LOCALIZATIONS.get(DEFAULT_LANGUAGE, {}))
    merged.update(LOCALIZATIONS.get(language, {}))
    return merged


TTS_COLORS = [ # default ones, used for QR codes decription
    "White", "Brown", "Red", "Orange", "Yellow",
    "Green", "Teal", "Blue", "Purple", "Pink",
]
game_state = {color: [] for color in TTS_COLORS}
drop_zones = []
mobile_buttons = []
hand_zone_colors = []
seated_colors = []
STATE_LOCK = threading.RLock()
LUA_TIMEOUT_SECONDS = 10
ACTION_TIMEOUT_SECONDS = 10
last_lua_contact_at = None
helper_instance = None
retired_helpers = set()
sync_run = None
table_ready = False
update_sequences = {}
pending_actions = {}
pending_refresh = set()
interaction_requests = {}
next_interaction_id = 1
client_sessions = {}
color_owners = {}

INTERACTION_TTL_SECONDS = 90
INTERACTION_MAX_CARD_COUNT = 10

def drop_zone_visible_for_color(zone, color):
    allowed_colors = zone.get("allowed_colors")
    return allowed_colors is None or color in allowed_colors

def drop_zones_for_color(color):
    return [
        zone for zone in drop_zones
        if isinstance(zone, dict) and drop_zone_visible_for_color(zone, color)
    ]

def mobile_button_visible_for_color(button, color):
    allowed_colors = button.get("allowed_colors")
    return allowed_colors is None or color in allowed_colors

def mobile_buttons_for_color(color):
    return [
        button for button in mobile_buttons
        if isinstance(button, dict) and mobile_button_visible_for_color(button, color)
    ]

def lua_connection_status():
    return {"connected": last_lua_contact_at is not None, "ready": table_ready}


def emit_lua_status():
    socketio.emit("lua_status", lua_connection_status())


def begin_sync():
    global sync_run, table_ready
    sync_run = uuid.uuid4().hex
    table_ready = False
    update_sequences.clear()
    for action_id in list(pending_actions):
        finish_action(action_id, "uncertain")
    interaction_requests.clear()
    pending_refresh.clear()


def expire_lua_contact(now):
    global last_lua_contact_at
    if last_lua_contact_at is not None and now - last_lua_contact_at >= LUA_TIMEOUT_SECONDS:
        last_lua_contact_at = None
        begin_sync()
        emit_lua_status()
        emit_hand_state_to_all_colors()


def is_valid_tts_guid(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{6}", value) is not None


def lua_array(value):
    # An empty Lua table can arrive as an empty JSON object.
    if value == {}:
        return []
    if not isinstance(value, list):
        raise ValueError("expected an array")
    return value


def valid_color(color):
    return isinstance(color, str) and color in (*TTS_COLORS, "Black")


def valid_drop_zone(zone):
    if not isinstance(zone, dict):
        return False
    kind = zone.get("type")
    index = zone.get("snap_index")
    position = zone.get("position")
    return (
        kind in ("global_snap", "object_snap")
        and (kind != "object_snap" or is_valid_tts_guid(zone.get("object_guid")))
        and type(index) is int and index > 0
        and isinstance(zone.get("tag_key"), str) and bool(zone["tag_key"])
        and isinstance(position, dict)
        and all(type(position.get(axis)) in (int, float) and math.isfinite(position[axis]) for axis in ("x", "y", "z"))
    )


def sanitize_drop_zones(zones):
    zones = lua_array(zones)
    for zone in zones:
        if not valid_drop_zone(zone):
            raise ValueError("invalid drop zone")
        if zone.get("allowed_colors") is not None:
            zone["allowed_colors"] = sanitize_color_list(zone["allowed_colors"])
    return zones


def valid_mobile_button(button):
    if not isinstance(button, dict):
        return False
    click_function = button.get("click_function")
    owner_type = button.get("function_owner_type")
    return (
        isinstance(button.get("id"), str) and bool(button["id"])
        and is_valid_tts_guid(button.get("object_guid"))
        and isinstance(button.get("name"), str) and bool(button["name"])
        and isinstance(click_function, str)
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", click_function) is not None
        and owner_type in ("global", "object")
        and (owner_type == "global" or is_valid_tts_guid(button.get("function_owner_guid")))
    )


def sanitize_mobile_buttons(buttons):
    buttons = lua_array(buttons)
    for button in buttons:
        if not valid_mobile_button(button):
            raise ValueError("invalid button")
        if button.get("allowed_colors") is not None:
            button["allowed_colors"] = sanitize_color_list(button["allowed_colors"])
    return buttons


def sanitize_color_list(colors):
    colors = lua_array(colors)
    if not all(valid_color(color) for color in colors):
        raise ValueError("invalid player color")
    return list(dict.fromkeys(colors))


def occupied_colors():
    return [
        color for color in known_player_colors()
        if color_owners.get(color)
    ]

def color_is_occupied_by_other(color, client_id):
    owner = color_owners.get(color)
    return bool(owner and owner != client_id)

def active_color_for_client(client_id):
    if not client_id:
        return None
    for color, owner_client_id in color_owners.items():
        if owner_client_id == client_id:
            return color
    return None

def first_free_color(client_id=None):
    for color in known_player_colors():
        owner = color_owners.get(color)
        if not owner or owner == client_id:
            return color
    return None

def color_client_has_live_session(color, client_id):
    return any(
        session.get("color") == color and
        session.get("client_id") == client_id and
        not session.get("is_admin")
        for session in client_sessions.values()
    )

def socket_can_control_color(sid, color):
    session = client_sessions.get(sid)
    if not session or session.get("color") != color:
        return False
    if session.get("is_admin"):
        return True
    return color_owners.get(color) == session.get("client_id")

def emit_hand_state_to_color(color, room=None, is_admin=False, client_id=None):
    if room is None:
        for sid, session in list(client_sessions.items()):
            if session.get("color") == color:
                emit_hand_state_to_color(
                    color,
                    room=sid,
                    is_admin=session.get("is_admin", False),
                    client_id=session.get("client_id"),
                )
        return

    socketio.emit(
        'hand_updated',
        {
            'cards': game_state.get(color, []) if table_ready else [],
            'players': known_player_colors(),
            'hand_zone_colors': known_hand_zone_colors(),
            'seated_colors': known_seated_colors(),
            'drop_zones': drop_zones_for_color(color),
            'mobile_buttons': mobile_buttons_for_color(color),
            'occupied_colors': occupied_colors(),
            'lua_connection': lua_connection_status(),
            'is_admin': is_admin,
            'color': color,
            'client_id': client_id,
        },
        room=room or color,
    )
    emit_interactions_to_color(color, room=room)

def emit_occupancy_to_all_clients():
    for sid, session in list(client_sessions.items()):
        color = session.get("color")
        if color in game_state:
            emit_hand_state_to_color(
                color,
                room=sid,
                is_admin=session.get("is_admin", False),
                client_id=session.get("client_id"),
            )

def emit_hand_state_to_all_colors():
    for color in known_player_colors():
        emit_hand_state_to_color(color)

# 1. Lokale IP-Adresse ermitteln, damit die Handys den PC finden
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))
            return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return '127.0.0.1'

LOCAL_IP = None
PORT = 5001  # Port fuer das Handy-Webinterface


def get_server_ip():
    global LOCAL_IP
    if LAN_IP_OVERRIDE is not None:
        return LAN_IP_OVERRIDE
    if LOCAL_IP is None:
        LOCAL_IP = get_local_ip()
    return LOCAL_IP


def print_start_qr_codes():
    local_ip = get_server_ip()
    print("\n" + "="*50)
    print(f"SERVER GESTARTET! Lokale IP: {local_ip}")
    if IPv4Address(local_ip).is_loopback:
        print("[WARNUNG] Diese Adresse ist nur auf diesem PC erreichbar.")
        print("          Gib die IPv4-Adresse im selben Netz wie das Handy mit --lan-ip an.")
    print("Scanne den passenden QR-Code mit dem Handy:")
    for label, url in [
        ("Admin", f"http://{local_ip}:{PORT}/?admin=1"),
        ("Spieler", f"http://{local_ip}:{PORT}/?join=player"),
    ]:
        print(f"\n[{label}] -> {url}")
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(tty=False)
    print("="*50 + "\n")




def get_request_data(request):
    raw = request.get_data(cache=True, as_text=True)
    if request.is_json or raw.lstrip().startswith("{"):
        data = json.loads(raw)
    else:
        fields = list(request.form.items(multi=True))
        if len(fields) != 1:
            raise ValueError("expected a single JSON form field")
        key, value = fields[0]
        if key != "payload" and value:
            raise ValueError("invalid JSON form field")
        data = json.loads(value if key == "payload" else key)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def lua_input():
    try:
        address = ip_address(request.remote_addr)
        mapped = getattr(address, "ipv4_mapped", None)
        if not (address.is_loopback or (mapped and mapped.is_loopback)):
            raise ValueError
    except ValueError:
        return None, ({"status": "error", "message": "loopback required"}, 403)
    try:
        return get_request_data(request), None
    except ValueError as exc:
        return None, ({"status": "error", "message": str(exc)}, 400)


def tts_cache_filename_from_url(url):
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    path = parsed.path or ""
    ext = Path(path).suffix
    if not ext:
        ext = ".png"
    # TTS entfernt offenbar alle Nicht-Buchstaben/Zahlen
    base = re.sub(r"[^a-zA-Z0-9]", "", url)
    return base + ext

def sanitize_browser_image_url(url):
    if not isinstance(url, str):
        return ""
    value = url.strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme in {"http", "https"}:
        return value
    if not parsed.scheme and not parsed.netloc and value.startswith("/local_image/"):
        return value
    return ""

def find_tts_cached_image_url(original_url):
    if not original_url:
        return ""
    filename = tts_cache_filename_from_url(original_url)
    if not filename:
        return sanitize_browser_image_url(original_url)
    for cache_dir in TTS_IMAGE_CACHE_DIRS:
        path = cache_dir / filename
        if path.is_file():
            return f"http://{get_server_ip()}:{PORT}/local_image/{filename}"
    return sanitize_browser_image_url(original_url)

def safe_local_image_path(filename):
    if not isinstance(filename, str):
        return None
    requested = Path(filename)
    if requested.is_absolute() or requested.name != filename or ".." in requested.parts:
        return None
    for cache_dir in TTS_IMAGE_CACHE_DIRS:
        cache_root = cache_dir.resolve()
        path = (cache_root / requested.name).resolve()
        if path.parent == cache_root and path.is_file():
            return path
    return None
  
@app.route('/local_image/<path:filename>')
def local_image(filename):
    path = safe_local_image_path(filename)
    if path:
        return send_from_directory(str(path.parent), path.name)
    return "image not found", 404


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/health")
def lua_health():
    global helper_instance, last_lua_contact_at
    data, error = lua_input()
    if error:
        return error
    instance = data.get("helper")
    if not isinstance(instance, str) or not re.fullmatch(r"[0-9a-fA-F]{6}:[0-9]+", instance):
        return {"status": "error", "message": "invalid helper instance"}, 400

    with STATE_LOCK:
        now = time.monotonic()
        expire_lua_contact(now)
        if instance != helper_instance:
            if instance in retired_helpers or (
                last_lua_contact_at is not None
                and helper_instance.split(":", 1)[0] != instance.split(":", 1)[0]
            ):
                return {"status": "error", "message": "another helper is active"}, 409
            if helper_instance is not None:
                retired_helpers.add(helper_instance)
            helper_instance = instance
            begin_sync()
            last_lua_contact_at = None
        first_contact = last_lua_contact_at is None
        last_lua_contact_at = now
        if first_contact:
            emit_lua_status()
            emit_hand_state_to_all_colors()
        return {"status": "ok", "run": sync_run, "ready": table_ready}


def read_cards(cards):
    cards = lua_array(cards)
    guids = set()
    for card in cards:
        if not isinstance(card, dict) or not is_valid_tts_guid(card.get("guid")) or card["guid"] in guids:
            raise ValueError("invalid or duplicate card")
        guids.add(card["guid"])
        if not isinstance(card.get("face_down", False), bool):
            raise ValueError("invalid card orientation")
        for field in ("name", "desc", "image", "back_image"):
            if field in card and not isinstance(card[field], str):
                raise ValueError(f"invalid card {field}")
        card["image"] = find_tts_cached_image_url(card.get("image"))
        card["back_image"] = find_tts_cached_image_url(card.get("back_image"))
        decals = card.get("attached_decals") or []
        if isinstance(decals, dict):
            decals = decals.values()
        elif not isinstance(decals, list):
            raise ValueError("invalid decals")
        for decal in decals:
            if not isinstance(decal, dict):
                raise ValueError("invalid decal")
            custom = decal.get("CustomDecal") or {}
            if not isinstance(custom, dict):
                raise ValueError("invalid custom decal")
            if custom.get("ImageURL"):
                custom["ImageURL"] = find_tts_cached_image_url(custom["ImageURL"])
    return cards


def read_table_metadata(data):
    return {
        "drop_zones": sanitize_drop_zones(data["drop_zones"]),
        "mobile_buttons": sanitize_mobile_buttons(data["mobile_buttons"]),
        "hand_zone_colors": sanitize_color_list(data["hand_zone_colors"]),
        "seated_colors": sanitize_color_list(data["seated_colors"]),
    }


def accept_update(data, stream, *, initial=False):
    global last_lua_contact_at
    sequence = data.get("sequence")
    if type(sequence) is not int or sequence < 1:
        return {"status": "error", "message": "invalid update sequence"}, 400
    now = time.monotonic()
    expire_lua_contact(now)
    if (
        last_lua_contact_at is None or data.get("run") != sync_run
        or data.get("helper") != helper_instance or (not initial and not table_ready)
    ):
        return {"status": "error", "message": "resync required"}, 409
    if sequence <= update_sequences.get(stream, 0):
        return {"status": "ok", "stale": True}, 200
    if initial and table_ready:
        return {"status": "error", "message": "table already initialized"}, 409
    update_sequences[stream] = sequence
    last_lua_contact_at = now
    return None


def replace_table_metadata(metadata):
    global drop_zones, mobile_buttons, hand_zone_colors, seated_colors
    old = (drop_zones, mobile_buttons, hand_zone_colors, seated_colors)
    drop_zones = metadata["drop_zones"]
    mobile_buttons = metadata["mobile_buttons"]
    hand_zone_colors = metadata["hand_zone_colors"]
    seated_colors = metadata["seated_colors"]
    return old != (drop_zones, mobile_buttons, hand_zone_colors, seated_colors)


@app.post("/sync_snapshot")
def sync_snapshot():
    global table_ready
    data, error = lua_input()
    if error:
        return error
    try:
        hands = data["hands"]
        if not isinstance(hands, dict) or not all(valid_color(color) for color in hands):
            raise ValueError("invalid hands")
        metadata = read_table_metadata(data)
        if not set(metadata["hand_zone_colors"]).issubset(hands):
            raise ValueError("missing hands")
        cards_by_color = {color: read_cards(cards) for color, cards in hands.items()}
    except (KeyError, ValueError, OverflowError) as exc:
        return {"status": "error", "message": str(exc)}, 400
    with STATE_LOCK:
        error = accept_update(data, "snapshot", initial=True)
        if error:
            return error
        for color in dict.fromkeys([*TTS_COLORS, *game_state, *cards_by_color]):
            game_state[color] = cards_by_color.get(color, [])
        replace_table_metadata(metadata)
        table_ready = True
        emit_hand_state_to_all_colors()
        emit_lua_status()
    return {"status": "ok"}


@app.post("/update_hand")
def update_hand():
    data, error = lua_input()
    if error:
        return error
    try:
        color = data["color"]
        if not valid_color(color):
            raise ValueError("invalid player color")
        cards = read_cards(data["cards"])
    except (KeyError, ValueError, OverflowError) as exc:
        return {"status": "error", "message": str(exc)}, 400
    with STATE_LOCK:
        error = accept_update(data, ("hand", color))
        if error:
            return error
        if color not in game_state or game_state[color] != cards or data.get("force") is True:
            new_color = color not in game_state
            game_state[color] = cards
            if new_color:
                emit_hand_state_to_all_colors()
            else:
                emit_hand_state_to_color(color)
    return {"status": "ok"}


@app.post("/update_table")
def update_table():
    data, error = lua_input()
    if error:
        return error
    try:
        metadata = read_table_metadata(data)
    except (KeyError, ValueError, OverflowError) as exc:
        return {"status": "error", "message": str(exc)}, 400
    with STATE_LOCK:
        error = accept_update(data, "table")
        if error:
            return error
        added_colors = [color for color in metadata["hand_zone_colors"] if color not in game_state]
        for color in added_colors:
            game_state[color] = []
        if replace_table_metadata(metadata) or added_colors:
            emit_hand_state_to_all_colors()
    return {"status": "ok"}


@socketio.on("join")
def on_join(data):
    data = data if isinstance(data, dict) else {}
    color = data.get("color")
    client_id = str(data.get("client_id") or "").strip()
    is_admin = data.get("is_admin") is True
    language = client_language_from_data(data)
    sid = request.sid

    with STATE_LOCK:
        if not isinstance(color, str) or color not in game_state:
            emit("join_error", localized_payload("errors.invalid_player_color", language, field="error"))
            return
        if not client_id:
            emit("join_error", localized_payload("errors.missing_client_id", language, field="error"))
            return
        if not is_admin and color_is_occupied_by_other(color, client_id):
            emit("join_error", localized_payload("errors.color_occupied_by_other", language, {"color": color}, field="error"))
            return
        previous = client_sessions.get(sid)
        client_sessions[sid] = {"client_id": client_id, "color": color, "is_admin": is_admin, "language": language}
        if previous and previous["color"] != color:
            leave_room(previous["color"])
        if previous:
            release_color(previous)
        if not is_admin:
            color_owners[color] = client_id
        join_room(color)
        emit("join_success", {"color": color})
        emit_occupancy_to_all_clients()


def release_color(session):
    color = session["color"]
    client_id = session["client_id"]
    if (
        not session["is_admin"] and color_owners.get(color) == client_id
        and not color_client_has_live_session(color, client_id)
    ):
        color_owners.pop(color, None)


@socketio.on("disconnect")
def on_disconnect():
    with STATE_LOCK:
        session = client_sessions.pop(request.sid, None)
        if session:
            release_color(session)
            emit_occupancy_to_all_clients()


def known_player_colors():
    return list(game_state.keys())


def known_hand_zone_colors():
    return [color for color in hand_zone_colors if color in game_state]


def known_seated_colors():
    return [color for color in seated_colors if color in game_state]


def sanitize_guid_list(value):
    if not isinstance(value, list):
        return []
    result = []
    for guid in value:
        if isinstance(guid, str) and guid and guid not in result:
            result.append(guid)
    return result


def current_hand_guids(color):
    return {card.get("guid") for card in game_state.get(color, []) if isinstance(card, dict)}


def current_hand_cards(color):
    return [card for card in game_state.get(color, []) if isinstance(card, dict) and card.get("guid")]


def interaction_selection_cards(request_data):
    show_hidden = request_data.get("type") == "draw_random_hidden"
    cards = current_hand_cards(request_data.get("target_color"))
    if not show_hidden:
        return [{**card, "face_down": False} for card in cards]

    return [
        {
            "guid": card.get("guid"),
            "back_image": card.get("back_image") or "",
            "face_down": True,
            "scale_x": card.get("scale_x", 1),
            "scale_z": card.get("scale_z", 1),
            "sideways": card.get("sideways", False),
        }
        for card in cards
    ]


def cleanup_expired_interactions(now=None):
    now = time.monotonic() if now is None else now
    for request_id, data in list(interaction_requests.items()):
        if data["status"] != "processing" and now - data["created_at"] >= INTERACTION_TTL_SECONDS:
            del interaction_requests[request_id]
            emit_interaction_result(data, False, translate("errors.request_unavailable"), "errors.request_unavailable")
            emit_interactions_for_request(data)


def next_interaction_request_id():
    global next_interaction_id
    request_id = str(next_interaction_id)
    next_interaction_id += 1
    return request_id


def public_interaction_request(request_data):
    return {
        "id": request_data.get("id"),
        "type": request_data.get("type"),
        "from_color": request_data.get("from_color"),
        "target_color": request_data.get("target_color"),
        "count": request_data.get("count"),
        "status": request_data.get("status"),
    }


def interaction_summary_for_color(color):
    incoming = []
    outgoing = []
    for request_data in interaction_requests.values():
        if request_data.get("target_color") == color and request_data.get("status") == "pending":
            incoming.append(public_interaction_request(request_data))
        if request_data.get("from_color") == color:
            outgoing.append(public_interaction_request(request_data))
    return {
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
    }


def emit_interactions_to_color(color, room=None):
    if color not in game_state:
        return
    socketio.emit("interaction_updated", interaction_summary_for_color(color), room=room or color)


def emit_interactions_for_request(request_data):
    emit_interactions_to_color(request_data.get("from_color"))
    emit_interactions_to_color(request_data.get("target_color"))


def emit_interaction_result(request_data, ok, message, message_key=None, message_params=None):
    payload = {
        "ok": ok,
        "message": message,
        "request": public_interaction_request(request_data),
    }
    if message_key:
        payload["message_key"] = message_key
        payload["message_params"] = message_params or {}
    socketio.emit("interaction_result", payload, room=request_data.get("from_color"))
    socketio.emit("interaction_result", payload, room=request_data.get("target_color"))


def clamp_interaction_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if count < 1:
        return None
    return min(count, INTERACTION_MAX_CARD_COUNT)


def validate_interaction_target_message(from_color, target_color, count, language=None):
    if not isinstance(from_color, str) or from_color not in game_state:
        return localized_payload("errors.invalid_player_color", language)
    if target_color not in hand_zone_colors:
        return localized_payload("errors.invalid_other_player", language)
    if from_color not in hand_zone_colors:
        return localized_payload("errors.invalid_player_color", language)
    if target_color == from_color:
        return localized_payload("errors.choose_other_player", language)
    if len(current_hand_guids(target_color)) < count:
        return localized_payload("errors.not_enough_cards", language)
    return None


def require_ready(event, language, field="error"):
    expire_lua_contact(time.monotonic())
    if table_ready:
        return True
    emit(event, localized_payload("errors.tts_not_ready", language, field=field, ok=False))
    return False


def register_action(sid, color, action, guids, target=None, interaction=None):
    action_id = uuid.uuid4().hex
    pending_actions[action_id] = {
        "sid": sid, "color": color, "action": action, "target": target,
        "interaction": interaction, "deadline": time.monotonic() + ACTION_TIMEOUT_SECONDS,
    }
    return {
        "action": "card_action", "action_id": action_id, "helper": helper_instance, "run": sync_run,
        "color": color, "card_action": action, "guids_json": json.dumps(guids), "target": target,
    }


def finish_action(action_id, status, error_key="errors.action_failed"):
    action = pending_actions.pop(action_id, None)
    if action is None:
        return
    ok = status == "ok"
    if status == "uncertain":
        error_key = "errors.action_unconfirmed"
    if not ok:
        pending_refresh.add(action["color"])
        if action["action"] == "give_to_player":
            pending_refresh.add(action["target"])
    interaction = action["interaction"]
    if interaction is not None:
        interaction_requests.pop(interaction["id"], None)
        key = "interaction.cards_taken" if ok else error_key
        emit_interaction_result(interaction, ok, translate(key), key)
        emit_interactions_for_request(interaction)
    else:
        sid = action["sid"]
        payload = {"ok": ok, "action": action["action"], "action_id": action_id, "color": action["color"]}
        if not ok:
            payload.update(localized_payload(error_key, client_language_from_sid(sid), field="error"))
        socketio.emit("card_action_result", payload, to=sid)


def dispatch_action(message):
    try:
        get_tts_api_chatgpt().custom_message(message)
    except Exception as exc:
        print(f"[TTS] Card action delivery failed: {exc}")
        with STATE_LOCK:
            finish_action(message["action_id"], "uncertain")


@app.post("/action_result")
def action_result():
    data, error = lua_input()
    if error:
        return error
    action_id, status = data.get("action_id"), data.get("result")
    if not isinstance(action_id, str) or status not in ("ok", "rejected", "uncertain"):
        return {"status": "error", "message": "invalid action result"}, 400
    allowed_errors = (
        "errors.action_failed", "errors.invalid_target_player", "errors.invalid_player_color", "errors.card_not_in_current_hand",
        "errors.drop_target_changed", "errors.hand_order_changed",
    )
    error_key = data.get("error_key")
    if error_key not in allowed_errors:
        error_key = "errors.action_failed"
    with STATE_LOCK:
        if data.get("run") != sync_run or data.get("helper") != helper_instance:
            return {"status": "error", "message": "resync required"}, 409
        action = pending_actions.get(action_id)
        if action and time.monotonic() >= action["deadline"]:
            status = "uncertain"
        finish_action(action_id, status, error_key)
    return {"status": "ok"}


def request_tts_hand_sync_for_colors(colors):
    with STATE_LOCK:
        if not table_ready:
            return
        run, helper = sync_run, helper_instance
        colors = list(dict.fromkeys(color for color in colors if color in game_state))
    try:
        if colors:
            get_tts_api_chatgpt().custom_message({
                "action": "request_hand_sync", "helper": helper, "run": run,
                "colors": colors, "force": True,
            })
    except Exception as exc:
        print(f"[TTS] Hand sync request failed: {exc}")


def maintenance_once():
    with STATE_LOCK:
        now = time.monotonic()
        expire_lua_contact(now)
        cleanup_expired_interactions(now)
        for action_id, action in list(pending_actions.items()):
            if now >= action["deadline"]:
                finish_action(action_id, "uncertain")
        colors = list(pending_refresh)
        pending_refresh.clear()
    if colors:
        socketio.start_background_task(request_tts_hand_sync_for_colors, colors)


def maintain_table():
    while True:
        maintenance_once()
        socketio.sleep(0.5)


class LuaHeartbeatLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not ('"POST /health HTTP/' in message and '" 200 ' in message)


def lua_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def send_mobile_button_action_to_tts(player_color, button, alt_click=False):
    click_function = button.get("click_function")
    if not isinstance(click_function, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", click_function):
        raise ValueError("invalid click_function")

    target_guid = button.get("object_guid")
    owner_type = button.get("function_owner_type")
    owner_guid = button.get("function_owner_guid")
    alt_click_lua = "true" if alt_click else "false"
    script = f"""
local target = getObjectFromGUID({lua_string(target_guid)})
if not target then
    error("Mobile button target object not found: " .. {lua_string(target_guid)})
end
local clickFunction = {click_function}
if type(clickFunction) ~= "function" then
    error("Mobile button function not found: " .. {lua_string(click_function)})
end
return clickFunction(target, {lua_string(player_color)}, {alt_click_lua})
"""

    tts_api = get_tts_api_chatgpt()
    if owner_type == "global":
        return tts_api.execute(script)
    return tts_api.execute_on_object(script, owner_guid)


# 4. Befehle vom Handy empfangen: Aktionen auf eine oder mehrere Karten
def matching_drop_zone(color, value):
    if not isinstance(value, str):
        return None
    try:
        target = json.loads(value)
        if not valid_drop_zone(target):
            return None
    except (ValueError, OverflowError):
        return None
    identity = ("type", "object_guid", "snap_index", "tag_key", "position")
    for zone in drop_zones_for_color(color):
        if all(zone.get(key) == target.get(key) for key in identity):
            return json.dumps({**zone, "spread_cards": target.get("spread_cards") is True})
    return None


@socketio.on("card_action")
def on_card_action(data):
    data = data if isinstance(data, dict) else {}
    action_name, color = data.get("action"), data.get("color")
    guids = sanitize_guid_list(data.get("guids"))
    target = data.get("target")
    sid = request.sid
    with STATE_LOCK:
        language = client_language_from_sid(sid)
        if not require_ready("card_action_result", language):
            return
        error = None
        if not isinstance(color, str) or color not in game_state:
            error = "errors.invalid_player_color"
        elif not socket_can_control_color(sid, color):
            error = "errors.not_controlling_color"
        elif action_name not in ("reorder_hand", "flip_cards", "play_to_table", "play_to_zone", "give_to_player"):
            error = "errors.unknown_player_action"
        elif not guids:
            error = "errors.no_cards_selected"
        elif not set(guids).issubset(current_hand_guids(color)):
            error = "errors.card_not_in_current_hand"
        elif action_name == "reorder_hand" and set(guids) != current_hand_guids(color):
            error = "errors.hand_order_changed"
        elif action_name == "give_to_player" and (target not in hand_zone_colors or target == color):
            error = "errors.invalid_target_player"
        elif action_name == "play_to_zone":
            target = matching_drop_zone(color, target)
            if target is None:
                error = "errors.drop_target_changed"
        if error:
            emit("card_action_result", localized_payload(
                error, language, field="error", ok=False, action=action_name, color=color,
            ))
            return
        message = register_action(sid, color, action_name, guids, target)
    dispatch_action(message)


@socketio.on('interaction_request')
def on_interaction_request(data):
    data = data if isinstance(data, dict) else {}
    with STATE_LOCK:
        language = client_language_from_sid(request.sid)
        if not require_ready("interaction_result", language, field="message"):
            return
        cleanup_expired_interactions()
        from_color = data.get('color')
        target_color = data.get('target_color')
        interaction_type = data.get('interaction_type')
        count = clamp_interaction_count(data.get('count'))

        if interaction_type not in ('draw_random_hidden', 'pick_open'):
            emit('interaction_result', localized_payload('errors.unknown_player_action', language, ok=False))
            return
        if count is None:
            emit('interaction_result', localized_payload('errors.invalid_card_count', language, ok=False))
            return

        error = validate_interaction_target_message(from_color, target_color, count, language)
        if error:
            error["ok"] = False
            emit('interaction_result', error)
            return
        if not socket_can_control_color(request.sid, from_color):
            emit('interaction_result', localized_payload('errors.not_controlling_color', language, ok=False))
            return

        request_data = {
            "id": next_interaction_request_id(),
            "type": interaction_type,
            "from_color": from_color,
            "target_color": target_color,
            "count": count,
            "status": "pending",
            "created_at": time.monotonic(),
        }
        interaction_requests[request_data["id"]] = request_data
        emit_interactions_for_request(request_data)
        emit('interaction_result', {
            'ok': True,
            'message': translate('interaction.request_sent', language),
            'message_key': 'interaction.request_sent',
            'message_params': {},
            'request': public_interaction_request(request_data),
        })


@socketio.on('interaction_response')
def on_interaction_response(data):
    data = data if isinstance(data, dict) else {}
    with STATE_LOCK:
        language = client_language_from_sid(request.sid)
        if not require_ready("interaction_result", language, field="message"):
            return
        cleanup_expired_interactions()
        request_data = interaction_requests.get(str(data.get('request_id') or ''))
        color = data.get('color')
        request_id = str(data.get('request_id') or '')
        accepted = data.get('accepted') is True

        if not request_data or request_data.get("status") != "pending":
            emit('interaction_result', localized_payload('errors.request_unavailable', language, ok=False))
            return
        if request_data.get("target_color") != color:
            emit('interaction_result', localized_payload('errors.request_not_for_you', language, ok=False))
            return
        if not socket_can_control_color(request.sid, color):
            emit('interaction_result', localized_payload('errors.not_controlling_color', language, ok=False))
            return

        if not accepted:
            interaction_requests.pop(request_id, None)
            emit_interaction_result(request_data, False, translate('interaction.request_denied', PC_LANGUAGE), 'interaction.request_denied')
            emit_interactions_for_request(request_data)
            return

        error = validate_interaction_target_message(
            request_data.get("from_color"),
            request_data.get("target_color"),
            request_data.get("count"),
            language,
        )
        if error:
            interaction_requests.pop(request_id, None)
            emit_interaction_result(
                request_data,
                False,
                error.get("message"),
                error.get("message_key"),
                error.get("message_params"),
            )
            emit_interactions_for_request(request_data)
            return

        request_data["status"] = "selecting"
        request_data["approved_at"] = time.monotonic()
        socketio.emit(
            'interaction_open_pick',
            {
                'request': public_interaction_request(request_data),
                'cards': interaction_selection_cards(request_data),
            },
            room=request_data.get("from_color"),
        )
        emit_interactions_for_request(request_data)


@socketio.on('interaction_open_selection_request')
def on_interaction_open_selection_request(data):
    data = data if isinstance(data, dict) else {}
    with STATE_LOCK:
        language = client_language_from_sid(request.sid)
        if not require_ready("interaction_result", language, field="message"):
            return
        cleanup_expired_interactions()
        request_data = interaction_requests.get(str(data.get('request_id') or ''))
        color = data.get('color')
        request_id = str(data.get('request_id') or '')

        if not request_data or request_data.get("status") != "selecting":
            emit('interaction_result', localized_payload('errors.selection_unavailable', language, ok=False))
            return
        if request_data.get("from_color") != color:
            emit('interaction_result', localized_payload('errors.selection_not_for_you', language, ok=False))
            return
        if not socket_can_control_color(request.sid, color):
            emit('interaction_result', localized_payload('errors.not_controlling_color', language, ok=False))
            return

        emit('interaction_open_pick', {
            'request': public_interaction_request(request_data),
            'cards': interaction_selection_cards(request_data),
        })


@socketio.on("interaction_pick_cards")
def on_interaction_pick_cards(data):
    data = data if isinstance(data, dict) else {}
    color = data.get("color")
    request_id = str(data.get("request_id") or "")
    guids = sanitize_guid_list(data.get("guids"))
    sid = request.sid
    with STATE_LOCK:
        language = client_language_from_sid(sid)
        if not require_ready("interaction_result", language, field="message"):
            return
        cleanup_expired_interactions()
        interaction = interaction_requests.get(request_id)
        error = None
        if not interaction or interaction["status"] != "selecting":
            error = "errors.selection_unavailable"
        elif interaction["from_color"] != color:
            error = "errors.selection_not_for_you"
        elif not socket_can_control_color(sid, color):
            error = "errors.not_controlling_color"
        elif len(guids) != interaction["count"]:
            error = "errors.pick_exact_count"
        elif color not in hand_zone_colors:
            error = "errors.invalid_target_player"
        if error:
            emit("interaction_result", localized_payload(error, language, ok=False))
            return

        source = interaction["target_color"]
        if not set(guids).issubset(current_hand_guids(source)):
            interaction_requests.pop(request_id)
            key = "errors.card_not_in_other_hand"
            emit_interaction_result(interaction, False, translate(key, language), key)
            emit_interactions_for_request(interaction)
            return

        interaction["status"] = "processing"
        message = register_action(sid, source, "give_to_player", guids, color, interaction)
        emit_interactions_for_request(interaction)
    dispatch_action(message)


@socketio.on('interaction_cancel')
def on_interaction_cancel(data):
    data = data if isinstance(data, dict) else {}
    with STATE_LOCK:
        language = client_language_from_sid(request.sid)
        if not require_ready("interaction_result", language, field="message"):
            return
        cleanup_expired_interactions()
        request_data = interaction_requests.get(str(data.get('request_id') or ''))
        color = data.get('color')
        request_id = str(data.get('request_id') or '')

        if not request_data or request_data["status"] == "processing":
            emit('interaction_result', localized_payload('errors.request_unavailable', language, ok=False))
            return
        if color not in (request_data.get("from_color"), request_data.get("target_color")):
            emit('interaction_result', localized_payload('errors.request_not_yours', language, ok=False))
            return
        if not socket_can_control_color(request.sid, color):
            emit('interaction_result', localized_payload('errors.not_controlling_color', language, ok=False))
            return

        interaction_requests.pop(request_id, None)
        emit_interaction_result(
            request_data,
            False,
            translate('interaction.request_cancelled', PC_LANGUAGE),
            'interaction.request_cancelled',
        )
        emit_interactions_for_request(request_data)


@socketio.on('mobile_button_action')
def on_mobile_button_action(data):
    data = data if isinstance(data, dict) else {}
    with STATE_LOCK:
        player_color = data.get('color')
        button_id = data.get('button_id')
        alt_click = bool(data.get('alt_click'))
        language = client_language_from_sid(request.sid)
        if not require_ready('mobile_button_action_result', language):
            return

        if not isinstance(player_color, str) or player_color not in game_state:
            emit('mobile_button_action_result', localized_payload('errors.invalid_player_color', language, field='error', ok=False))
            return

        if not socket_can_control_color(request.sid, player_color):
            emit('mobile_button_action_result', localized_payload('errors.not_controlling_color', language, field='error', ok=False))
            return

        visible_buttons = mobile_buttons_for_color(player_color)
        button = next((item for item in visible_buttons if item.get('id') == button_id), None)
        if not button:
            emit('mobile_button_action_result', localized_payload('errors.mobile_button_unavailable', language, field='error', ok=False))
            return

    print(f"[ACTION] {player_color}: mobile_button -> {button.get('name')} ({button_id}), alt_click={alt_click}")
    try:
        send_mobile_button_action_to_tts(player_color, button, alt_click)
    except Exception as exc:
        emit(
            'mobile_button_action_result',
            localized_payload(
                'errors.mobile_button_execution_failed',
                language,
                {'error': str(exc)},
                field='error',
                ok=False,
            )
        )
        return
    emit('mobile_button_action_result', {
        'ok': True,
        'button_id': button_id,
    })


@socketio.on("admin_sync_all_hands")
def on_admin_sync_all_hands(data=None):
    with STATE_LOCK:
        session = client_sessions.get(request.sid)
        language = client_language_from_sid(request.sid)
        if not session or not session.get("is_admin"):
            emit("admin_sync_result", localized_payload("errors.admin_required", language, field="error", ok=False))
            return
        if not require_ready("admin_sync_result", language):
            return
        colors = known_player_colors()
    socketio.start_background_task(request_tts_hand_sync_for_colors, colors)
    emit("admin_sync_result", localized_payload(
        "settings.sync_all_hands_sent", language, {"count": len(colors)}, ok=True,
    ))


@app.route('/socket.io.js')
def serve_socketio_js():
    # Liefert die lokal gespeicherte JavaScript-Datei an das Handy aus
    socketio_path = resource_file_path("socket.io.js")
    return send_from_directory(socketio_path.parent, socketio_path.name)

@app.route('/assign_player')
def assign_player_color():
    language = request_language()
    client_id = request.args.get("client_id", "").strip()
    with STATE_LOCK:
        color = active_color_for_client(client_id) or first_free_color(client_id)
    if not client_id or not color:
        return render_error_page(translate("errors.all_colors_occupied", language), language)
    return redirect(f"/?color={color}")

def render_error_page(message, language=None):
    language = resolve_language([language, PC_LANGUAGE])
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="{{ language }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ title }}</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #121212;
                color: #eee;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                padding: 20px;
            }
            .message {
                max-width: 420px;
                padding: 18px;
                border: 1px solid #555;
                border-radius: 10px;
                background: #222;
                text-align: center;
                line-height: 1.4;
            }
        </style>
    </head>
    <body><div class="message">{{ message }}</div></body>
    </html>
    """, message=message, language=language, title=translate("app.title", language))

# script quelle: https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.8.1/socket.io.js
# 5. Das HTML-Interface
@app.route('/')
def index():
    language = request_language()
    if request.args.get("join") == "player":
        return render_template_string("""
        <!DOCTYPE html>
        <html lang="{{ language }}">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ assign_title }}</title>
        </head>
        <body>
            <script>
                const key = 'tts_mobile_companion_client_id';
                let clientId = localStorage.getItem(key);
                if (!clientId) {
                    clientId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
                    localStorage.setItem(key, clientId);
                }
                window.location.replace(`/assign_player?client_id=${encodeURIComponent(clientId)}`);
            </script>
        </body>
        </html>
        """, language=language, assign_title=translate("assign.title", language))

    try:
        mobile_ui_template = resource_file_path("mobile_ui.html").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[FEHLER] mobile_ui.html konnte nicht geladen werden: {exc}")
        return render_error_page(
            "mobile_ui.html konnte nicht geladen werden. Bitte pruefe, ob die Datei neben server_mobile_actions.py liegt oder in der PyInstaller-Version mitgepackt wurde.",
            language,
        ), 500

    return render_template_string(
        mobile_ui_template,
        language=language,
        title=translate("app.title", language),
        i18n=client_i18n(language),
        tr=lambda key, params=None: translate(key, language, params),
    )

if __name__ == '__main__':
    start_args = parse_start_arguments()
    apply_start_arguments(start_args)

    print("[START] Starte den Catan Companion Server auf Port 5001...")
    if TTS_API_DEBUG_INCOMING or TTS_API_DEBUG_OUTGOING:
        print(
            "[DEBUG] TTS External API Debug aktiv: "
            f"incoming={TTS_API_DEBUG_INCOMING}, outgoing={TTS_API_DEBUG_OUTGOING}"
        )
    logging.getLogger('werkzeug').addFilter(LuaHeartbeatLogFilter())
    print_start_qr_codes()
    socketio.start_background_task(maintain_table)
    # Startet den Server im lokalen Netzwerk
    # debug=False ist wichtig, da der Debug-Modus den Shutdown-Code oft doppelt ausfuehrt
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False)
    # Beenden mit Strg+C ist tatsaechlich vorgesehen von socketio um zu beenden


