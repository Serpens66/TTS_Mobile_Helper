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
- Load the workshop content ingame "additive" to your TTS game.  
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
