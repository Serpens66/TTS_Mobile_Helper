import socket
import json
import time
import qrcode
import sys
import locale
import argparse
from os import environ
from pathlib import Path
from flask import Flask, render_template_string, request, send_from_directory, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room
import engineio.async_drivers.threading  # needed by PyInstaller for async_mode="threading"
from urllib.parse import unquote
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
TTS_API_DEBUG_INCOMING = False
TTS_API_DEBUG_OUTGOING = False


def parse_start_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="TTS Mobile Companion Server"
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
    global TTS_API_DEBUG_INCOMING, TTS_API_DEBUG_OUTGOING
    TTS_API_DEBUG_INCOMING = bool(args.debug_tts_api or args.debug_tts_incoming)
    TTS_API_DEBUG_OUTGOING = bool(args.debug_tts_api or args.debug_tts_outgoing)


def get_tts_api_chatgpt():
    global tts_api_chatgpt
    if tts_api_chatgpt is None:
        # Instanz der uebersetzten Rust-Klasse erstellen:
        # https://github.com/LucasOe/tts-external-api/tree/master
        tts_api_chatgpt = ExternalEditorApi_chatgpt(
            debug_incoming=TTS_API_DEBUG_INCOMING,
            debug_outgoing=TTS_API_DEBUG_OUTGOING,
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
last_lua_contact_at = None
interaction_requests = {}
next_interaction_id = 1
client_sessions = {}
color_owners = {}

INTERACTION_TTL_SECONDS = 90
INTERACTION_MAX_CARD_COUNT = 10

def drop_zone_visible_for_color(zone, color):
    allowed_colors = zone.get("allowed_colors")
    if not allowed_colors:
        return True
    if not isinstance(allowed_colors, list):
        return True
    return color in allowed_colors

def drop_zones_for_color(color):
    return [
        zone for zone in drop_zones
        if isinstance(zone, dict) and drop_zone_visible_for_color(zone, color)
    ]

def mobile_button_visible_for_color(button, color):
    allowed_colors = button.get("allowed_colors")
    if not allowed_colors:
        return True
    if not isinstance(allowed_colors, list):
        return True
    return color in allowed_colors

def mobile_buttons_for_color(color):
    return [
        button for button in mobile_buttons
        if isinstance(button, dict) and mobile_button_visible_for_color(button, color)
    ]

def mark_lua_contact():
    global last_lua_contact_at
    first_contact = last_lua_contact_at is None
    last_lua_contact_at = time.time()
    return first_contact

def lua_connection_status():
    return {
        "connected": last_lua_contact_at is not None,
        "last_contact_at": last_lua_contact_at,
    }

def is_valid_tts_guid(value):
    return isinstance(value, str) and re.match(r"^[0-9a-fA-F]{6}$", value) is not None

def valid_drop_zone(zone):
    if not isinstance(zone, dict):
        return False
    if zone.get("type") == "global_snap":
        return zone.get("snap_index") is not None
    if zone.get("type") == "object_snap":
        return is_valid_tts_guid(zone.get("object_guid")) and zone.get("snap_index") is not None
    return False

def sanitize_drop_zones(zones):
    if not isinstance(zones, list):
        return None
    return [
        zone for zone in zones
        if valid_drop_zone(zone)
    ]

def valid_mobile_button(button):
    if not isinstance(button, dict):
        return False
    click_function = button.get("click_function")
    owner_type = button.get("function_owner_type")
    return (
        bool(button.get("id")) and
        is_valid_tts_guid(button.get("object_guid")) and
        bool(button.get("name")) and
        isinstance(click_function, str) and
        bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", click_function)) and
        owner_type in {"global", "object"} and
        (owner_type == "global" or is_valid_tts_guid(button.get("function_owner_guid")))
    )

def sanitize_mobile_buttons(buttons):
    if not isinstance(buttons, list):
        return None
    return [
        button for button in buttons
        if valid_mobile_button(button)
    ]

def sanitize_color_list(colors):
    if not isinstance(colors, list):
        return None
    result = []
    for color in colors:
        if isinstance(color, str) and color in game_state and color not in result:
            result.append(color)
    return result

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
            'cards': game_state.get(color, []),
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
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

LOCAL_IP = None
PORT = 5001  # Port fuer das Handy-Webinterface


def get_server_ip():
    global LOCAL_IP
    if LOCAL_IP is None:
        LOCAL_IP = get_local_ip()
    return LOCAL_IP


def print_start_qr_codes():
    local_ip = get_server_ip()
    print("\n" + "="*50)
    print(f"SERVER GESTARTET! Lokale IP: {local_ip}")
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
  data = {}
  try:
    # Da TTS laut Doku als application/x-www-form-urlencoded sendet, ist request.form hier randvoll mit unseren Daten! https://api.tabletopsimulator.com/webrequest/manager/#post
    if request.form:
      # 1. Wir holen uns die Liste aller Formular-Schluessel
      form_keys = list(request.form.keys())
      if form_keys:
        raw_url_encoded_text = form_keys[0] # wir holen uns den String aus Position 0!
        clean_json_text = unquote(raw_url_encoded_text) # 2. Dekodieren der Prozentzeichen
        if clean_json_text.endswith('='): # Falls TTS am Ende ein '=' anhaengt, schneiden wir es ab
          clean_json_text = clean_json_text[:-1]
        # 3. Parsen des sauberen Text-Strings als echtes Dictionary
        data = json.loads(clean_json_text)
        if not isinstance(data, dict):
          data = dict(data)
    else:
      print("[WARNUNG] get_request_data: Request enthielt keine Formulardaten.")
  except Exception as e:
      print(f"[CRITICAL] get_request_data: Fehler beim Formular-Parsing: {e}")
  # if data:
    # print("[DEBUG] get_request_data: data ist: ",data)
  return data
  

def tts_cache_filename_from_url(url):
    if not isinstance(url, str) or not url:
        return None
    parsed = urlparse(url)
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
    parsed = urlparse(value)
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


@app.route('/health', methods=['GET', 'POST'])
def health():
    if mark_lua_contact():
        emit_hand_state_to_all_colors()
    return {"status": "ok"}


  
# 2. HTTP-Endpunkt fuer TTS (TTS schickt hier Karten-Updates hin , Optimiert mit Dubletten-Filter)
@app.route('/update_hand', methods=['POST'])
def update_hand():
    first_lua_contact = mark_lua_contact()
    data = get_request_data(request)
    player_color = data.get("color")
    cards = data.get("cards", [])
    zones = data.get("drop_zones")
    buttons = data.get("mobile_buttons")
    colors = data.get("hand_zone_colors")
    seats = data.get("seated_colors")
    global drop_zones, mobile_buttons, hand_zone_colors, seated_colors
    sanitized_zones = sanitize_drop_zones(zones)
    if sanitized_zones is not None:
        drop_zones = sanitized_zones
    sanitized_buttons = sanitize_mobile_buttons(buttons)
    if sanitized_buttons is not None:
        mobile_buttons = sanitized_buttons
    sanitized_colors = sanitize_color_list(colors)
    colors_changed = sanitized_colors is not None and sanitized_colors != hand_zone_colors
    if sanitized_colors is not None:
        hand_zone_colors = sanitized_colors
    sanitized_seats = sanitize_color_list(seats)
    seats_changed = sanitized_seats is not None and sanitized_seats != seated_colors
    if sanitized_seats is not None:
        seated_colors = sanitized_seats
    if not player_color:
        return {"status": "error", "message": "missing color"}, 400
    if not isinstance(cards, list):
        return {"status": "error", "message": "cards must be a list"}, 400
    # Falls TTS eine Farbe sendet, die Python noch nicht kennt:
    if player_color not in game_state:
        game_state[player_color] = []
    # Lokale TTS-Cache-Bilder bevorzugen, Internet-URL als Fallback behalten
    for card in cards:
        if not isinstance(card, dict):
            continue
        card["image"] = find_tts_cached_image_url(card.get("image"))
        card["back_image"] = find_tts_cached_image_url(card.get("back_image"))
        decals = card.get("attached_decals") or []
        if isinstance(decals, dict):
            decals = decals.values()
        for decal in decals:
            if not isinstance(decal, dict):
                continue
            custom_decal = decal.get("CustomDecal") or {}
            image_url = custom_decal.get("ImageURL")
            if image_url:
                custom_decal["ImageURL"] = find_tts_cached_image_url(image_url)
    old_state = json.dumps(game_state[player_color],sort_keys=True,ensure_ascii=False)
    new_state = json.dumps(cards,sort_keys=True,ensure_ascii=False)
    if old_state != new_state:
        game_state[player_color] = cards
        emit_hand_state_to_color(player_color)
        print(f"[NETZWERK] Hand von Spieler {player_color} aktualisiert ({len(cards)} Karten).")
    elif colors_changed or seats_changed or first_lua_contact:
        emit_hand_state_to_all_colors()
    if first_lua_contact and old_state != new_state:
        emit_hand_state_to_all_colors()

    return {"status": "success"}


@app.route('/update_drop_zones', methods=['POST'])
def update_drop_zones():
    mark_lua_contact()
    data = get_request_data(request)
    zones = data.get("drop_zones")
    colors = data.get("hand_zone_colors")
    seats = data.get("seated_colors")
    sanitized_zones = sanitize_drop_zones(zones)
    if sanitized_zones is None:
        return {"status": "error", "message": "drop_zones must be a list"}, 400
    global drop_zones, hand_zone_colors, seated_colors
    old_state = json.dumps(drop_zones, sort_keys=True, ensure_ascii=False)
    new_state = json.dumps(sanitized_zones, sort_keys=True, ensure_ascii=False)
    if old_state != new_state:
        drop_zones = sanitized_zones
        print(f"[NETZWERK] Ablagezonen aktualisiert ({len(drop_zones)} Ziele).")
    sanitized_colors = sanitize_color_list(colors)
    if sanitized_colors is not None:
        hand_zone_colors = sanitized_colors
    sanitized_seats = sanitize_color_list(seats)
    if sanitized_seats is not None:
        seated_colors = sanitized_seats
    emit_hand_state_to_all_colors()
    return {"status": "success"}


@app.route('/update_mobile_buttons', methods=['POST'])
def update_mobile_buttons():
    mark_lua_contact()
    data = get_request_data(request)
    buttons = data.get("mobile_buttons")
    colors = data.get("hand_zone_colors")
    seats = data.get("seated_colors")
    sanitized_buttons = sanitize_mobile_buttons(buttons)
    if sanitized_buttons is None:
        return {"status": "error", "message": "mobile_buttons must be a list"}, 400
    global mobile_buttons, hand_zone_colors, seated_colors
    old_state = json.dumps(mobile_buttons, sort_keys=True, ensure_ascii=False)
    new_state = json.dumps(sanitized_buttons, sort_keys=True, ensure_ascii=False)
    if old_state != new_state:
        mobile_buttons = sanitized_buttons
        print(f"[NETZWERK] Mobile-Buttons aktualisiert ({len(mobile_buttons)} Ziele).")
    sanitized_colors = sanitize_color_list(colors)
    if sanitized_colors is not None:
        hand_zone_colors = sanitized_colors
    sanitized_seats = sanitize_color_list(seats)
    if sanitized_seats is not None:
        seated_colors = sanitized_seats
    emit_hand_state_to_all_colors()
    return {"status": "success"}


# 3. WebSockets: Handy verbindet sich und waehlt seine Farbe (Raum)
@socketio.on('join')
def on_join(data):
    color = data.get('color')
    client_id = str(data.get('client_id') or '').strip()
    is_admin = bool(data.get('is_admin'))
    language = client_language_from_data(data)
    sid = request.sid

    if color not in game_state:
        emit('join_error', localized_payload('errors.invalid_player_color', language, field='error'))
        return
    if not client_id:
        emit('join_error', localized_payload('errors.missing_client_id', language, field='error'))
        return

    previous_session = client_sessions.get(sid)
    if previous_session and previous_session.get("color") != color:
        leave_room(previous_session.get("color"))
        previous_color = previous_session.get("color")
        if (
            not previous_session.get("is_admin") and
            color_owners.get(previous_color) == previous_session.get("client_id")
        ):
            color_owners.pop(previous_color, None)

    if not is_admin and color_is_occupied_by_other(color, client_id):
        emit(
            'join_error',
            localized_payload('errors.color_occupied_by_other', language, {'color': color}, field='error')
        )
        return

    if not is_admin:
        color_owners[color] = client_id

    client_sessions[sid] = {
        "client_id": client_id,
        "color": color,
        "is_admin": is_admin,
        "language": language,
    }

    join_room(color)
    role = "Admin" if is_admin else "Spieler"
    print(f"[VERBINDUNG] {role}-Smartphone fuer {color} angemeldet.")
    emit_hand_state_to_color(color, room=sid, is_admin=is_admin, client_id=client_id)
    emit_occupancy_to_all_clients()
    get_tts_api_chatgpt().custom_message({
        "action": "request_hand_sync",
        "color": color,
        "force": True,
    })
    return


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    session = client_sessions.pop(sid, None)
    if not session:
        return
    color = session.get("color")
    client_id = session.get("client_id")
    if (
        not session.get("is_admin") and
        color_owners.get(color) == client_id and
        not color_client_has_live_session(color, client_id)
    ):
        color_owners.pop(color, None)
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


def cleanup_expired_interactions():
    now = time.time()
    expired_ids = [
        request_id for request_id, request_data in interaction_requests.items()
        if now - request_data.get("created_at", now) > INTERACTION_TTL_SECONDS
    ]
    for request_id in expired_ids:
        request_data = interaction_requests.pop(request_id, None)
        if request_data:
            emit_interaction_result(
                request_data,
                False,
                "Die Anfrage ist abgelaufen.",
            )


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
    cleanup_expired_interactions()
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
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    return min(count, INTERACTION_MAX_CARD_COUNT)


def validate_interaction_target_message(from_color, target_color, count, language=None):
    if from_color not in game_state:
        return localized_payload("errors.invalid_player_color", language)
    if target_color not in known_player_colors():
        return localized_payload("errors.invalid_other_player", language)
    if target_color == from_color:
        return localized_payload("errors.choose_other_player", language)
    if len(current_hand_guids(target_color)) < count:
        return localized_payload("errors.not_enough_cards", language)
    return None


def send_card_action_to_tts(player_color, action_name, guids, target=None):
    payload = {
        "action": "card_action",
        "color": player_color,
        "card_action": action_name,
        "guids_json": json.dumps(guids),
        "target": target,
    }
    get_tts_api_chatgpt().custom_message(payload)


def request_tts_hand_sync(color, force=True):
    if color not in game_state:
        return
    get_tts_api_chatgpt().custom_message({
        "action": "request_hand_sync",
        "color": color,
        "force": force,
    })


def request_tts_hand_sync_for_colors(colors, delays=(0.15, 0.8, 1.6)):
    unique_colors = []
    for color in colors:
        if color in game_state and color not in unique_colors:
            unique_colors.append(color)
    for delay in delays:
        for color in unique_colors:
            threading.Timer(delay, request_tts_hand_sync, args=(color, True)).start()


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
@socketio.on('card_action')
def on_card_action(data):
    action_name = data.get('action')
    player_color = data.get('color')
    guids = sanitize_guid_list(data.get('guids'))
    target = data.get('target')
    language = client_language_from_sid(request.sid)

    if player_color not in game_state:
        emit('card_action_result', localized_payload('errors.invalid_player_color', language, field='error', ok=False))
        return

    if not socket_can_control_color(request.sid, player_color):
        emit('card_action_result', localized_payload('errors.not_controlling_color', language, field='error', ok=False))
        return

    if not guids:
        emit('card_action_result', localized_payload('errors.no_cards_selected', language, field='error', ok=False))
        return

    hand_guids = current_hand_guids(player_color)
    if any(guid not in hand_guids for guid in guids):
        emit('card_action_result', localized_payload('errors.card_not_in_current_hand', language, field='error', ok=False))
        return

    if action_name == 'give_to_player' and target not in known_player_colors():
        emit('card_action_result', localized_payload('errors.invalid_target_player', language, field='error', ok=False))
        return

    print(f"[ACTION] {player_color}: {action_name} -> {guids}, target={target}")
    send_card_action_to_tts(player_color, action_name, guids, target)

    emit('card_action_result', {
        'ok': True,
        'action': action_name,
        'guids': guids,
    })


@socketio.on('interaction_request')
def on_interaction_request(data):
    from_color = data.get('color')
    target_color = data.get('target_color')
    interaction_type = data.get('interaction_type')
    count = clamp_interaction_count(data.get('count'))
    language = client_language_from_sid(request.sid)

    if interaction_type not in {'draw_random_hidden', 'pick_open'}:
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
        "created_at": time.time(),
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
    color = data.get('color')
    request_id = str(data.get('request_id') or '')
    accepted = bool(data.get('accepted'))
    request_data = interaction_requests.get(request_id)
    language = client_language_from_sid(request.sid)

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
    request_data["approved_at"] = time.time()
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
    color = data.get('color')
    request_id = str(data.get('request_id') or '')
    request_data = interaction_requests.get(request_id)
    language = client_language_from_sid(request.sid)

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


@socketio.on('interaction_pick_cards')
def on_interaction_pick_cards(data):
    color = data.get('color')
    request_id = str(data.get('request_id') or '')
    guids = sanitize_guid_list(data.get('guids'))
    request_data = interaction_requests.get(request_id)
    language = client_language_from_sid(request.sid)

    if not request_data or request_data.get("status") != "selecting":
        emit('interaction_result', localized_payload('errors.selection_unavailable', language, ok=False))
        return
    if request_data.get("from_color") != color:
        emit('interaction_result', localized_payload('errors.selection_not_for_you', language, ok=False))
        return
    if not socket_can_control_color(request.sid, color):
        emit('interaction_result', localized_payload('errors.not_controlling_color', language, ok=False))
        return
    if len(guids) != request_data.get("count"):
        emit('interaction_result', localized_payload('errors.pick_exact_count', language, ok=False))
        return

    target_hand_guids = current_hand_guids(request_data.get("target_color"))
    if any(guid not in target_hand_guids for guid in guids):
        interaction_requests.pop(request_id, None)
        emit_interaction_result(
            request_data,
            False,
            translate('errors.card_not_in_other_hand', PC_LANGUAGE),
            'errors.card_not_in_other_hand',
        )
        emit_interactions_for_request(request_data)
        return

    send_card_action_to_tts(
        request_data.get("target_color"),
        "give_to_player",
        guids,
        request_data.get("from_color"),
    )
    request_tts_hand_sync_for_colors([
        request_data.get("target_color"),
        request_data.get("from_color"),
    ])
    interaction_requests.pop(request_id, None)
    emit_interaction_result(
        request_data,
        True,
        translate('interaction.cards_taken', PC_LANGUAGE),
        'interaction.cards_taken',
    )
    emit_interactions_for_request(request_data)


@socketio.on('interaction_cancel')
def on_interaction_cancel(data):
    color = data.get('color')
    request_id = str(data.get('request_id') or '')
    request_data = interaction_requests.get(request_id)
    language = client_language_from_sid(request.sid)

    if not request_data:
        emit('interaction_result', localized_payload('errors.request_unavailable', language, ok=False))
        return
    if color not in {request_data.get("from_color"), request_data.get("target_color")}:
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
    player_color = data.get('color')
    button_id = data.get('button_id')
    alt_click = bool(data.get('alt_click'))
    language = client_language_from_sid(request.sid)

    if player_color not in game_state:
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


@socketio.on('admin_sync_all_hands')
def on_admin_sync_all_hands(data=None):
    session = client_sessions.get(request.sid)
    language = client_language_from_sid(request.sid)
    if not session or not session.get("is_admin"):
        emit('admin_sync_result', localized_payload('errors.admin_required', language, field='error', ok=False))
        return

    colors = known_hand_zone_colors() or known_player_colors()
    request_tts_hand_sync_for_colors(colors)
    emit('admin_sync_result', localized_payload(
        'settings.sync_all_hands_sent',
        language,
        {'count': len(colors)},
        ok=True,
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
    i18n_json = json.dumps(client_i18n(language), ensure_ascii=False)
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
        i18n_json=i18n_json,
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
    print_start_qr_codes()
    # Startet den Server im lokalen Netzwerk
    # debug=False ist wichtig, da der Debug-Modus den Shutdown-Code oft doppelt ausfuehrt
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False)
    # Beenden mit Strg+C ist tatsaechlich vorgesehen von socketio um zu beenden


