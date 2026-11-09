# Tabletop Simulator Mobile Helper

Play Tabletop Simulator in local Hotseat mode on a shared screen. Keep the table visible from the spectator view while players use their phones to see and control their own hands.

## Features

- **Live hand updates and card actions.** View, sort, flip, play, and give cards from a phone. Request a random face-down card or choose from another player's open hand after they approve the request.
- **Player and admin views.** Use separate QR codes for players and for the host. A player controls one color and the admin can switch between colors.
- **Drop targets and game buttons.** Add tagged snap points as destinations for played cards and use existing TTS object buttons from the phone.
- **Twelve interface languages.** The page uses the browser's preferred language when a translation is available.
- **Local network play.** The helper serves the interface and its Socket.IO client locally, and can reuse images already cached by TTS on the host PC.

## Quick start

1. Load your game in Tabletop Simulator. Add the [Workshop helper](https://steamcommunity.com/sharedfiles/filedetails/?id=3739147243) to the existing table using **Additive Load**, or copy [the Lua script](helper_object_mobile_actions.lua) into a TTS object's script and use **Save & Play**.
2. Download and extract the [Windows release](https://github.com/Serpens66/TTS_Mobile_Helper/releases). Run `TTSMobileHelper.exe` from the extracted folder on the PC running TTS. Keep the accompanying files in that folder.
3. Connect the phones to the same local network as the PC. A local Wi-Fi hotspot also works. On a trusted network, scan the **Player** QR code on each player's phone and the **Admin** QR code on the host's phone. The player link assigns an available color.

When running the current source or a build made from it, load the matching Lua script from this checkout into the helper object. The bundled Python server and the Lua helper exchange a versioned table snapshot before enabling actions.

The helper itself runs on the LAN. Download the Workshop content in advance for offline play. Card images that TTS has not cached may still need to load from their original URLs. Anyone on the network who opens the admin link can use the admin view.

### Run from source

Use Python 3.9 or later and run these commands from the project folder.

```powershell
python -m pip install -r requirements.txt
python server_mobile_actions.py
```

## Troubleshooting

| If you see | Try |
| --- | --- |
| The phone cannot open the QR link | Check that the phone and PC are on the same network. Open `http://<PC-IP>:5001/` from the phone. If the QR code shows the wrong address, start the current source with `python server_mobile_actions.py --lan-ip 192.168.1.100`, using the PC's IPv4 address on that network. The option also works in Windows builds made from this source. |
| The page opens but waits for TTS | Check that the Lua helper is loaded on the active table and the server is running on the TTS PC. |
| You need logs to diagnose TTS communication | Start with `--debug-tts-api` for both directions, or use `--debug-tts-incoming` or `--debug-tts-outgoing`. To enable logging in TTS, set `local DEBUG = true` in the helper object's Lua script. |

## Customization in TTS

### Card drop zones

Create or edit a snap point and add one of these tags.

| Tag | Result |
| --- | --- |
| `TTSmobile_MyDropZone` | Displays **MyDropZone** for all player colors. |
| `TTSmobile_MyDropZone_For_Yellow_Red` | Displays **MyDropZone** for Yellow and Red. |

In TTS, a tagged snap point only snaps cards that share a tag with it. To retain snapping for untagged cards, add a second, untagged snap point at the same position.

### Usage of TTS buttons

TTS object buttons can be triggered from phones. Buttons with the same name, tooltip, and color visibility are listed once. To control visibility, add tags to the object that owns the buttons.

| Tag | Result |
| --- | --- |
| `TTSmobile_For_Orange` | Shows the object's buttons for Orange. |
| `TTSmobileHideButtons` | Hides the object's buttons on phones. |

### Screenshots

<img width="1280" height="591" alt="TTSmobile_2" src="https://github.com/user-attachments/assets/2e1967bf-facb-4d0f-a45f-6dc759577cd6" />
<img width="591" height="1280" alt="TTSmobile_3" src="https://github.com/user-attachments/assets/ad91eddf-7913-4134-a574-ba7bca054fb8" />
<img width="591" height="1280" alt="TTSmobile_4" src="https://github.com/user-attachments/assets/75fd151e-a9b6-476d-823b-93ff54abefc2" />
<img width="591" height="1280" alt="TTSmobile_5" src="https://github.com/user-attachments/assets/a2d51796-da9e-4a5d-9bf0-ac5871751e5a" />
<img width="591" height="1280" alt="TTSmobile_6" src="https://github.com/user-attachments/assets/1b1b381e-0450-4786-8882-14f56908c180" />
<img width="591" height="1280" alt="TTSmobile_7" src="https://github.com/user-attachments/assets/0d628969-035a-44cf-a9c1-628d0778a008" />
<img width="591" height="1280" alt="TTSmobile_8" src="https://github.com/user-attachments/assets/30930f2d-241b-4aea-bc18-c74d7c7d61b3" />

## Languages

The mobile interface ships with English, German, Spanish, French, Italian, Portuguese, Dutch, Polish, Russian, Simplified Chinese, Japanese, and Korean. Translation files are in [localization/](localization/). The page uses the server PC's language if the browser does not request a supported language, and English is the fallback for missing strings. Card names and descriptions come from the game.

## How it works

| Part | Role |
| --- | --- |
| [Lua helper](helper_object_mobile_actions.lua) | Runs inside TTS and sends hand, drop target, and button updates over HTTP to the server on the same PC. |
| [Python server](server_mobile_actions.py) | Serves the phone interface on port 5001 and sends updates to browsers via Socket.IO. |
| [Mobile interface](mobile_ui.html), [CSS](static/mobile_ui.css), and [JavaScript](static/mobile_ui.js) | Display cards and controls and send player actions back to the server. |
| [TTS adapter](tts_api_chatgpt.py) | Sends actions back to TTS through the External Editor API. |

## Build on Windows

Run from the project directory.

```powershell
python -m pip install -r requirements.txt PyInstaller
.\build_pyinstaller.bat
```

The executable and its companion files are written to `dist/TTSMobileHelper/`. Distribute the whole folder when packaging a Windows release. To build with a portable Python installation, install the same dependencies with that interpreter and pass its executable path.

```powershell
.\build_pyinstaller.bat -Python "C:/path/to/python.exe"
```

## Tests

Run `python -m unittest discover -s tests -v` after installing the Python dependencies. For changes to the Lua helper, also test the matching Lua and Python versions on a separate TTS table.

## Credits

Built with help from ChatGPT Codex, the [Tabletop Simulator scripting documentation](https://api.tabletopsimulator.com/intro/), and the [External Editor API documentation](https://api.tabletopsimulator.com/externaleditorapi/). The Python adapter draws on [LucasOe's TTS External API wrapper](https://github.com/LucasOe/tts-external-api).
