# Tabletop Simulator (Steam) Mobile Helper  
Show hand cards from game Tabletop Simulator on your mobile phone and interact with them, other players and buttons.  
  
- Use this to play the TTS game on one big screen (in my case touch) locally with players sitting around it in real life. The players can use their mobile phone to see and interact with their hand cards, this way other players can not see the handcards.
- Works by creating a local network from the hardware (eg. PC/Laptop) that runs TTS and connects the mobile phones to it (for better safety dont use it in public network).  
- Works without internet connection (the PC/Laptop should have internet once to download workhop files).  
- The TTSMobileHelper.exe was compiled using PyInstaller, so you can run it without installing python yourself. But you can also instead run the server_mobile_actions.py script with your local python installation, in this case install all dependencies manually with pip.  
  
  
I wrote this with help of ChatGPT-Codex, the official documentations:  
https://api.tabletopsimulator.com/externaleditorapi/  
https://api.tabletopsimulator.com/intro/  
and https://github.com/LucasOe/tts-external-api/tree/master (converted by Codex to python)  
  
# Usage
- Subscribe to the lua helper script on the steam workshop:  https://steamcommunity.com/sharedfiles/filedetails/?id=3739147243  
- Download the release from github for the compiled version or the loose files from github if you have a python installation: https://github.com/Serpens66/TTS_Mobile_Helper/releases    
- Load the workshop content ingame "additive" to your TTS game (or save the content from "helper_object_mobile_actions.lua" to the script of an object within TTS).  
- Make sure your mobile phone(s) are in the same network like your PC/Laptop. Does not require internet, can also be a Wifi Hotspot without internet acces.
- Start the TTSMobileHelper.exe (or the server_mobile_actions.py script. For debugging start it with "python server_mobile_actions.py --debug-tts-api" and set "local Debug = true" in the lua script of the helper object within TTS)  
- Scan the QR code shown in the python console with your mobile phone (admin or player. admins are able to control each player, while players are only able to control one colour)
- Your mobile phones should now show the Interface and you should be connected.

# Customization in TTS:
## To define Card Drop zones to be displayed on mobile: 
- Create "Snap Point" in TTS and rightclick it.
- Add a Tag to it like "TTSmobile_MyDropZone", this will show this as card drop zone on mobile phones for all players with the name "MyDropZone".
- Or use a tag like "TTSmobile_MyDropZone_For_Yellow_Red", this will show this as card drop zone on mobile phones for yellow and red player with the name "MyDropZone".
- Keep in mind that tags on Snap Points will make cards only snap to it, if the cards and the point have at least one tag in common. So basically it disables the snap functionality for them. If you want the snap functionality create another Snap Point without a tag and move it at the very same position.
## Usage of TTS Buttons:
- All buttons in TTS are displayed on mobile to be pressed for all players (only one if there are multiple ones with the same name and same description).
- To limit the display of a button to specific player(s) add a tag like this to the object which contains the button(s): "TTSmobile_For_Orange".
- To not display the buttons of an object on mobile phones (eg. some helper buttons which are not supposed to be pressed) add to the object the tag: "TTSmobileHideButtons".

<img width="1280" height="591" alt="TTSmobile_2" src="https://github.com/user-attachments/assets/2e1967bf-facb-4d0f-a45f-6dc759577cd6" />
<img width="591" height="1280" alt="TTSmobile_3" src="https://github.com/user-attachments/assets/ad91eddf-7913-4134-a574-ba7bca054fb8" />
<img width="591" height="1280" alt="TTSmobile_4" src="https://github.com/user-attachments/assets/75fd151e-a9b6-476d-823b-93ff54abefc2" />
<img width="591" height="1280" alt="TTSmobile_5" src="https://github.com/user-attachments/assets/a2d51796-da9e-4a5d-9bf0-ac5871751e5a" />
<img width="591" height="1280" alt="TTSmobile_6" src="https://github.com/user-attachments/assets/1b1b381e-0450-4786-8882-14f56908c180" />
<img width="591" height="1280" alt="TTSmobile_7" src="https://github.com/user-attachments/assets/0d628969-035a-44cf-a9c1-628d0778a008" />
<img width="591" height="1280" alt="TTSmobile_8" src="https://github.com/user-attachments/assets/30930f2d-241b-4aea-bc18-c74d7c7d61b3" />

