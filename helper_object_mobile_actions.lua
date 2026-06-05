
-- lua script fuer Tabletop Simulator 

-- scripting API: https://api.tabletopsimulator.com/intro/

-- object.lua direkt im Workshop-Objekt

-- debug.traceback does not work unfortunately and the games error message also does not mention the line of error..

-- ingame in TTS brauchen Snap Points die als Ablageort fuer Karten erkannt werden sollen den Tag: "TTSmobile_Abwurfstapel" usw.
-- wenn ein Stapel nur fuer eine bestimmte Farbe ist, dann diese mit reinschreiben zb. TTSmobile_Abwurfstapel_For_Yellow_Blue_Red
-- und fuer Buttons die nur fuer bestimmte Farben angezeigt werden muss das beinhaltene Objekt den Tag TTSmobile_For_Yellow usw. 
-- falls fuer ein Objekt keine Buttons im Handy angezeigt werden sollen, kann der Tag TTSmobileHideButtons verwendet werden

local DEBUG = false
local SERVER_URLS = {
    health = "http://127.0.0.1:5001/health",
    update_hand = "http://127.0.0.1:5001/update_hand",
    update_drop_zones = "http://127.0.0.1:5001/update_drop_zones",
    update_mobile_buttons = "http://127.0.0.1:5001/update_mobile_buttons"
}
local TRACKED_COLORS = {}
local last_sent_states = {}
local known_card_flips = {}
local last_sent_drop_zones_json = ""
local pending_drop_zone_scan = false
local last_sent_mobile_buttons_json = ""
local pending_mobile_button_scan = false
local python_server_connected = false
local pending_python_server_check = false

function dlog(msg,...)
    if DEBUG then
        log(msg,...)
    end
end

function safeCall_TTSmobile(label, fallback, callback)
    local ok, result = pcall(callback)
    if ok then
        return result
    end
    dlog("Mobile Companion SafeCall fehlgeschlagen (" .. tostring(label) .. "): " .. tostring(result))
    return fallback
end

function safeObjectCall_TTSmobile(obj, methodName, fallback)
    if not obj or not methodName then
        return fallback
    end
    local okMethod, method = pcall(function()
        return obj[methodName]
    end)
    if not okMethod then
        dlog("Mobile Companion Objektmethode nicht lesbar (" .. tostring(methodName) .. "): " .. tostring(method))
        return fallback
    end
    if not method then
        return fallback
    end
    return safeCall_TTSmobile(methodName, fallback, function()
        return method()
    end)
end

function safeObjectTag_TTSmobile(obj)
    return safeCall_TTSmobile("object.tag", nil, function()
        return obj and obj.tag or nil
    end)
end

function safeGetAllObjects_TTSmobile()
    return safeCall_TTSmobile("getAllObjects", {}, function()
        return getAllObjects() or {}
    end)
end

function safeGetPlayer_TTSmobile(color)
    if not color then
        return nil
    end
    return safeCall_TTSmobile("Player " .. tostring(color), nil, function()
        return Player[color]
    end)
end

function getHandTransformForColor_TTSmobile(color)
    local player = safeGetPlayer_TTSmobile(color)
    if not player then
        return nil
    end
    return safeCall_TTSmobile("Player.getHandTransform " .. tostring(color), nil, function()
        return player.getHandTransform()
    end)
end

function getHandObjectsForColor_TTSmobile(color)
    local player = safeGetPlayer_TTSmobile(color)
    if not player then
        return {}
    end
    return safeCall_TTSmobile("Player.getHandObjects " .. tostring(color), {}, function()
        return player.getHandObjects() or {}
    end)
end

function resetSentState_TTSmobile()
    for _, color in ipairs(TRACKED_COLORS) do
        last_sent_states[color] = ""
    end
    last_sent_drop_zones_json = ""
    last_sent_mobile_buttons_json = ""
end

function onPythonServerConnected_TTSmobile(reason)
    resetSentState_TTSmobile()
    scheduleDropZoneScan_TTSmobile("Python Server verbunden: " .. tostring(reason), 0.1)
    scheduleMobileButtonScan_TTSmobile("Python Server verbunden: " .. tostring(reason), 0.1)
    scanAndSendAllHands_TTSmobile("Python Server verbunden: " .. tostring(reason))
end

function setPythonServerConnected_TTSmobile(connected, reason)
    local wasConnected = python_server_connected
    python_server_connected = connected == true
    if python_server_connected and not wasConnected then
        dlog("Python Server verbunden (" .. tostring(reason) .. ")")
        onPythonServerConnected_TTSmobile(reason)
    elseif not python_server_connected and wasConnected then
        dlog("Python Server nicht erreichbar (" .. tostring(reason) .. ")")
    end
end

function schedulePythonServerConnectionCheck_TTSmobile(reason, delay)
    if pending_python_server_check then
        return
    end
    pending_python_server_check = true
    Wait.time(function()
        pending_python_server_check = false
        checkPythonServerConnection_TTSmobile(reason)
    end, delay or 1.0)
end

function checkPythonServerConnection_TTSmobile(reason)
    WebRequest.post(
        SERVER_URLS["health"],
        JSON.encode({
            source = "tts_mobile"
        }),
        function(request)
            if not request or request.is_error then
                setPythonServerConnected_TTSmobile(false, (request and request.error) or reason)
                schedulePythonServerConnectionCheck_TTSmobile("Reconnect nach Health-Fehler", 2.0)
            else
                setPythonServerConnected_TTSmobile(true, reason or "Health")
            end
        end
    )
end

function requirePythonServer_TTSmobile(reason)
    if python_server_connected then
        return true
    end
    schedulePythonServerConnectionCheck_TTSmobile(reason, 0.5)
    return false
end

function handlePythonServerRequestResult_TTSmobile(request, label)
    if not request or request.is_error then
        dlog(tostring(label) .. " fehlgeschlagen: " .. tostring(request and request.error or "keine Antwort"))
        setPythonServerConnected_TTSmobile(false, label)
        schedulePythonServerConnectionCheck_TTSmobile(label, 1.0)
    else
        setPythonServerConnected_TTSmobile(true, label)
    end
end

function onLoad(save_state)
    dlog("onLoad Mobile Companion Helper aktiv")
    TRACKED_COLORS = Player.getAvailableColors()
    resetSentState_TTSmobile()
    schedulePythonServerConnectionCheck_TTSmobile("onLoad", 0.2)
end


local pending_hand_scans = {}

function scheduleHandScan_TTSmobile(color, reason, delay)
    if not color then
        return
    end
    if not requirePythonServer_TTSmobile(reason or "Handscan") then
        return
    end
    delay = delay or 0.1
    if pending_hand_scans[color] then
        return
    end
    pending_hand_scans[color] = true
    Wait.time(function()
        pending_hand_scans[color] = false
        scanAndSendHand_TTSmobile(color, reason .. " delayed")
    end, delay)
end

function getColorForCardInHand_TTSmobile(card)
    if not card then
        return nil
    end
    local cardGuid = safeObjectCall_TTSmobile(card, "getGUID", nil)
    if not cardGuid then
        return nil
    end
    for _, color in ipairs(TRACKED_COLORS) do
        local handObjects = getHandObjectsForColor_TTSmobile(color)
        for _, obj in ipairs(handObjects) do
            if obj and safeObjectCall_TTSmobile(obj, "getGUID", nil) == cardGuid then
                return color
            end
        end
    end
    return nil
end

function getHandZoneColor_TTSmobile(zone)
    if not zone then
        return nil
    end
    local data = safeObjectCall_TTSmobile(zone, "getData", nil)
    if data and data.HandColor then
        return data.HandColor
    end
    return nil
end

function onObjectDrop(player_color, object)
    -- dlog("onObjectDrop: " .. tostring(player_color) .. "," .. tostring(object))
    if not requirePythonServer_TTSmobile("onObjectDrop") then
        return
    end
    scheduleDropZoneScan_TTSmobile("Objekt gedroppt", 0.5)
    scheduleMobileButtonScan_TTSmobile("Objekt gedroppt", 0.5)
    if object and safeObjectTag_TTSmobile(object) == "Card" then
        Wait.time(function()
            local handColor = getColorForCardInHand_TTSmobile(object)
            if handColor then
                scheduleHandScan_TTSmobile(
                    handColor,
                    "Karte in Hand gedroppt",
                    0.1
                )
            end
        end, 0.1)
    end
end

function onObjectSpawn(object)
    if not requirePythonServer_TTSmobile("onObjectSpawn") then
        return
    end
    scheduleDropZoneScan_TTSmobile("Objekt gespawnt", 0.5)
    scheduleMobileButtonScan_TTSmobile("Objekt gespawnt", 0.5)
end

function onObjectDestroy(object)
    if not requirePythonServer_TTSmobile("onObjectDestroy") then
        return
    end
    scheduleDropZoneScan_TTSmobile("Objekt geloescht", 0.5)
    scheduleMobileButtonScan_TTSmobile("Objekt geloescht", 0.5)
end

function onObjectStateChange(object, old_guid)
    if not requirePythonServer_TTSmobile("onObjectStateChange") then
        return
    end
    scheduleDropZoneScan_TTSmobile("Objektzustand geaendert", 0.5)
    scheduleMobileButtonScan_TTSmobile("Objektzustand geaendert", 0.5)
end

function onObjectEnterZone(zone, object)
    if not requirePythonServer_TTSmobile("onObjectEnterZone") then
        return
    end
    dlog("onObjectEnterZone")
    if zone and safeObjectTag_TTSmobile(zone) == "Hand" and object and safeObjectTag_TTSmobile(object) == "Card" then
        local objectGuid = safeObjectCall_TTSmobile(object, "getGUID", nil)
        if objectGuid then
            known_card_flips[objectGuid] = nil
        end
        Wait.time(function()
            local handColor = getColorForCardInHand_TTSmobile(object)
            if handColor then
                scheduleHandScan_TTSmobile(
                    handColor,
                    "Karte betreten",
                    0.1
                )
            end
        end, 0.1)
    end
end

function onObjectLeaveZone(zone, object)
    if not requirePythonServer_TTSmobile("onObjectLeaveZone") then
        return
    end
    dlog("onObjectLeaveZone")
    if zone and safeObjectTag_TTSmobile(zone) == "Hand" and object and safeObjectTag_TTSmobile(object) == "Card" then
        local color = getHandZoneColor_TTSmobile(zone)
        if color then
            scheduleHandScan_TTSmobile(
                color,
                "Karte verlassen",
                0.1
            )
        else
            scanAndSendAllHands_TTSmobile("Karte verlassen fallback")
        end
    end
end


function onExternalMessage(data)
    local ok, err = pcall(function()
        handleExternalMessage_TTSmobile(data)
    end)
    if not ok then
        log(
            "Mobile Companion onExternalMessage fehlgeschlagen fuer action " ..
            tostring(data and data.action) ..
            ": " ..
            tostring(err)
        )
    end
end

function handleExternalMessage_TTSmobile(data)
    dlog("onExternalMessage")
    setPythonServerConnected_TTSmobile(true, "onExternalMessage")
    if not data or not data.action then
        return
    end
    if data.action == "play_card" then
        playCardFromMobile(data.color, data.guid)
        return
    end
    if data.action == "card_action" then
        local guids = {}
        if data.guids_json then
            local ok, decoded = pcall(function()
                return JSON.decode(data.guids_json)
            end)
            if ok and decoded then
                guids = decoded
            end
        elseif data.guid then
            guids = { data.guid }
        end
        handleCardAction_TTSmobile(
            data.color,
            data.card_action,
            guids,
            data.target
        )
        return
    end
    if data.action == "request_hand_sync" then
        requestHandSync_TTSmobile(data.color, data.force)
        return
    end
end



function requestHandSync_TTSmobile(color, force)
    if not color then
        return
    end
    if not requirePythonServer_TTSmobile("request_hand_sync") then
        return
    end
    if force then
        last_sent_states[color] = ""
    end
    scheduleDropZoneScan_TTSmobile("request_hand_sync", 0.1)
    scheduleMobileButtonScan_TTSmobile("request_hand_sync", 0.1)
    scanAndSendHand_TTSmobile(color, "request_hand_sync")
end


function getActualFaceDown_TTSmobile(card)
    if not card then
        return false
    end
    if card.is_face_down ~= nil then
        return card.is_face_down
    end
    local rot = safeObjectCall_TTSmobile(card, "getRotation", nil)
    local rotZ = rot and rot.z or nil
    if rotZ == nil then
        local data = safeObjectCall_TTSmobile(card, "getData", nil)
        rotZ = data and data.Transform and data.Transform.rotZ or 0
    end
    rotZ = math.abs(rotZ or 0) % 360
    return rotZ > 90 and rotZ < 270
end

function getKnownFaceDown_TTSmobile(card)
    if not card then
        return false
    end
    local cardGuid = safeObjectCall_TTSmobile(card, "getGUID", nil)
    local knownFlip = cardGuid and known_card_flips[cardGuid] or nil
    if knownFlip ~= nil then
        return knownFlip
    end
    return getActualFaceDown_TTSmobile(card)
end

function getYawFromRotation_TTSmobile(rotation, fallbackYaw)
    if not rotation then
        return fallbackYaw or 0
    end
    return rotation.y or rotation[2] or fallbackYaw or 0
end

function getLeftRightAxisFromYaw_TTSmobile(yaw)
    local angle = math.rad(yaw or 0)
    return {
        math.cos(angle),
        -math.sin(angle)
    }
end

function placeCardsOnDropTarget_TTSmobile(cards, pos, yaw, spreadCards)
    local axis = getLeftRightAxisFromYaw_TTSmobile(yaw)
    placeCardsAtOrientedWorldPositionWithRotation_TTSmobile(
        cards,
        {x = pos.x, y = pos.y + 1.0, z = pos.z},
        getCardSpreadOffsets_TTSmobile(cards, axis, spreadCards),
        axis,
        yaw
    )
end

function getRotationWithYaw_TTSmobile(card, yaw)
    local current = card and card.getRotation() or nil
    if not current then
        return {0, yaw or 0, 0}
    end
    return {
        current.x or current[1] or 0,
        yaw or current.y or current[2] or 0,
        current.z or current[3] or 0
    }
end

function onObjectRotate(object, spin, flip, player_color, old_spin, old_flip)
    if not requirePythonServer_TTSmobile("onObjectRotate") then
        return
    end
    dlog("onObjectRotate flip: "..tostring(flip)..","..tostring(old_flip))
    if object and safeObjectTag_TTSmobile(object) == "Card" then
        local objectGuid = safeObjectCall_TTSmobile(object, "getGUID", nil)
        if objectGuid then
            known_card_flips[objectGuid] = flip
        end
        scanAndSendAllHands_TTSmobile("Karte rotiert")
    end
end

function playCardFromMobile(color, guid)
    handleCardAction_TTSmobile(color, "play_to_table", { guid }, nil)
end

function flipCardsFromMobile_TTSmobile(color, cards, guids)
    cards = cards or getCardsFromGuids_TTSmobile(guids)
    for _, card in ipairs(cards) do
        local guid = safeObjectCall_TTSmobile(card, "getGUID", nil)
        if guid then
            known_card_flips[guid] = not getKnownFaceDown_TTSmobile(card)
        end
        card.flip()
    end
    scheduleHandScan_TTSmobile(color, "Karten umgedreht", 0.1)
end

function getCardsFromGuids_TTSmobile(guids)
    local cards = {}
    if type(guids) ~= "table" then
        return cards
    end
    for _, guid in ipairs(guids) do
        local card = getObjectFromGUID(guid)
        if card and safeObjectTag_TTSmobile(card) == "Card" then
            table.insert(cards, card)
        else
            dlog("Karte nicht gefunden oder keine Karte: " .. tostring(guid))
        end
    end
    return cards
end

local ACTION_HANDLERS = nil
function getActionHandlers_TTSmobile()
    if not ACTION_HANDLERS then
        ACTION_HANDLERS = {
            reorder_hand = reorderHandFromMobile_TTSmobile,
            flip_cards = flipCardsFromMobile_TTSmobile,
            play_to_table = playCardsToTable_TTSmobile,
            play_to_zone = playCardsToDropZone_TTSmobile,
            give_to_player = giveCardsToPlayer_TTSmobile
        }
    end
    return ACTION_HANDLERS
end

function handleCardAction_TTSmobile(color, actionName, guids, target)
    if not color or not actionName then
        return
    end
    local handler = getActionHandlers_TTSmobile()[actionName]
    if handler then
        local cards = getCardsFromGuids_TTSmobile(guids)
        handler(color, cards, guids, target)
    else
        dlog("Unbekannte card_action: " .. tostring(actionName))
    end
end


function playCardsToTable_TTSmobile(color, cards)
    placeCardsInFrontOfHandZone_TTSmobile(color, cards)
    scheduleHandScan_TTSmobile(color, "Karten ausgespielt", 0.1)
end

function placeCardsInFrontOfHandZone_TTSmobile(color, cards)
    dlog("placeCardsInFrontOfHandZone_TTSmobile called for color " .. tostring(color) .. " with " .. tostring(#cards) .. " cards")
    if not cards or #cards == 0 or not color then
        return
    end
    local handZone = getHandZoneForColor(color)
    dlog("placeCardsInFrontOfHandZone_TTSmobile Handzone für " .. tostring(color) .. ": " .. tostring(handZone))
    local handTransform = getHandTransformForColor_TTSmobile(color)
    local handPos = nil
    local handRot = nil

    if handZone then
        handPos = handZone.getPosition()
        handRot = handZone.getRotation()
    elseif handTransform then
        handPos = handTransform.position
        handRot = handTransform.rotation
    end

    if not handPos then
        dlog("Keine Handzone fuer " .. tostring(color) .. " gefunden, kann Karten nicht vor der Handzone ausspielen.")
        return
    end

    local distanceFromHand = 6
    local moveAxis = "z"
    if handRot then
        local yaw = getYawFromRotation_TTSmobile(handRot, 0)
        local angle = math.rad(yaw)
        local rowAxisX = math.cos(angle)
        local rowAxisZ = -math.sin(angle)
        if math.abs(rowAxisZ) > math.abs(rowAxisX) then
            moveAxis = "x"
        end
    else
        local dirX = -handPos.x
        local dirZ = -handPos.z
        if math.abs(dirX) > math.abs(dirZ) then
            moveAxis = "x"
        end
    end

    local moveX = 0
    local moveZ = 0
    if moveAxis == "x" then
        moveX = handPos.x <= 0 and distanceFromHand or -distanceFromHand
    else
        moveZ = handPos.z <= 0 and distanceFromHand or -distanceFromHand
    end

    local targetY = math.max(handPos.y + 1.0, 3.0)
    for i, card in ipairs(cards) do
        local cardPos = safeObjectCall_TTSmobile(card, "getPosition", nil)
        if cardPos then
            card.setLock(false)
            card.setPosition({
                cardPos.x + moveX,
                targetY + i * 0.05,
                cardPos.z + moveZ
            }, false, false)
        else
            dlog("Kartenposition konnte nicht gelesen werden, Karte wird nicht vor der Handzone ausgespielt.")
        end
    end
end

function playCardsToDropZone_TTSmobile(color, cards,guids, targetJson)
    if not color or not cards or #cards == 0 then
        return
    end
    local target = nil
    if targetJson then
        local ok, decoded = pcall(function()
            return JSON.decode(targetJson)
        end)
        if ok and decoded then
            target = decoded
        end
    end
    if not target then
        dlog("Drop-Ziel konnte nicht gelesen werden, spiele vor der Handzone: " .. tostring(targetJson))
        playCardsToTable_TTSmobile(color, cards)
        return
    end
    if target.type == "global_snap" then
        local snapPoints = Global.getSnapPoints() or {}
        local snap = snapPoints[target.snap_index]

        if not snap then
            dlog("Global Snap Point nicht gefunden: " .. tostring(target.snap_index))
            playCardsToTable_TTSmobile(color, cards)
            return
        end

        local pos = snap.position
        local yaw = getYawFromRotation_TTSmobile(snap.rotation, 180)
        local spreadCards = target.spread_cards == true
        dlog("Spiele Karten auf Global Snap-Ziel " .. tostring(target.name))

        placeCardsOnDropTarget_TTSmobile(cards, pos, yaw, spreadCards)

        scheduleHandScan_TTSmobile(color, "Karten auf Global Snap-Ziel gespielt", 0.3)
        return
    elseif target.type == "object_snap" then
        local obj = getObjectFromGUID(target.object_guid)
        if not obj then
            dlog("Snap-Zielobjekt nicht gefunden: " .. tostring(target.object_guid))
            playCardsToTable_TTSmobile(color, cards)
            return
        end
        local snapPoints = obj.getSnapPoints()
        local snap = snapPoints[target.snap_index]
        if not snap then
            dlog("Snap Point nicht gefunden: " .. tostring(target.snap_index))
            playCardsToTable_TTSmobile(color, cards)
            return
        end
        local pos = obj.positionToWorld(snap.position)
        local objYaw = getYawFromRotation_TTSmobile(obj.getRotation(), 0)
        local snapYaw = getYawFromRotation_TTSmobile(snap.rotation, 0)
        local yaw = objYaw + snapYaw
        local spreadCards = target.spread_cards == true
        dlog(
            "Spiele Karten auf Snap-Ziel " ..
            tostring(target.name) ..
            " bei x=" .. tostring(pos.x) ..
            ", y=" .. tostring(pos.y) ..
                ", z=" .. tostring(pos.z)
        )
        placeCardsOnDropTarget_TTSmobile(cards, pos, yaw, spreadCards)
        scheduleHandScan_TTSmobile(color, "Karten auf Snap-Ziel gespielt", 0.3)
        return
    end
    dlog("Unbekannter Drop-Zieltyp: " .. tostring(target.type))
    playCardsToTable_TTSmobile(color, cards)
end

function giveCardsToPlayer_TTSmobile(sourceColor, cards,guids, targetColor)
    if not sourceColor or not cards or #cards == 0 then
        return
    end
    if not targetColor or not safeGetPlayer_TTSmobile(targetColor) then
        dlog("Zielspieler ungueltig: " .. tostring(targetColor))
        return
    end
    local handTransform = getHandTransformForColor_TTSmobile(targetColor)
    if not handTransform then
        dlog("Kein HandTransform fuer Zielspieler: " .. tostring(targetColor))
        return
    end
    placeCardsInHandTransform_TTSmobile(cards, handTransform, 0)
    scheduleHandScan_TTSmobile(sourceColor, "Karten weitergegeben Quelle", 0.1)
    scheduleHandScan_TTSmobile(targetColor, "Karten weitergegeben Ziel", 0.1)
end

function reorderHandFromMobile_TTSmobile(color, cards, orderedGuids)
    dlog("reorderHandFromMobile start: " .. tostring(color))
    if not safeGetPlayer_TTSmobile(color) then
        dlog("reorderHandFromMobile ABORT: Player nicht gefunden: " .. tostring(color))
        return
    end
    local currentHandObjects = getHandObjectsForColor_TTSmobile(color)
    dlog("Aktuelle Handobjekte laut Player[" .. tostring(color) .. "]: " .. tostring(#currentHandObjects))
    local positions = {}
    for _, obj in ipairs(currentHandObjects) do
        if obj and safeObjectTag_TTSmobile(obj) == "Card" then
            table.insert(positions, obj.getPosition())
        end
    end

    local handTransform = getHandTransformForColor_TTSmobile(color)
    if not handTransform then
        dlog("reorderHandFromMobile ABORT: kein HandTransform fuer " .. tostring(color))
        return
    end
    local handPos = handTransform.position
    local handRot = handTransform.rotation
    local angle = math.rad(handRot.y)
    table.sort(positions, function(a, b)
        local ax = a.x - handPos.x
        local az = a.z - handPos.z
        local bx = b.x - handPos.x
        local bz = b.z - handPos.z
        local localA = ax * math.cos(angle) - az * math.sin(angle)
        local localB = bx * math.cos(angle) - bz * math.sin(angle)
        return localA < localB
    end)
    
    dlog("reorderHandFromMobile Karten aus GUIDs gefunden: " .. tostring(#cards))
    if #cards == 0 then
        dlog("reorderHandFromMobile ABORT: keine Karten aus GUIDs gefunden")
        return
    end
    if #positions == 0 then
        dlog("reorderHandFromMobile ABORT: keine Positionsvorlagen aus Handobjekten")
        return
    end
    for i, card in ipairs(cards) do
        local pos = positions[i] or positions[#positions]
        dlog(
            "Setze Karte #" .. tostring(i) ..
            " " .. tostring(card.getGUID()) ..
            " auf bestehende Handposition x=" .. tostring(pos.x) ..
            ", y=" .. tostring(pos.y) ..
            ", z=" .. tostring(pos.z)
        )
        card.setPosition({
            pos.x,
            pos.y + i * 0.03,
            pos.z
        }, false, false)
    end
    scheduleHandScan_TTSmobile(color, "Hand sortiert", 0.1)
end

function placeCardsAtWorldPosition_TTSmobile(cards, center, spacing, yaw)
    local count = #cards
    for i, card in ipairs(cards) do
        card.setLock(false)
        local offset = (i - (count + 1) / 2) * spacing
        card.setPosition({center[1] + offset, center[2] + (i * 0.05), center[3]}, false, false)
        if yaw ~= nil then
            card.setRotationSmooth(getRotationWithYaw_TTSmobile(card, yaw), false, false)
        end
    end
end

function placeCardsAtOrientedWorldPosition_TTSmobile(cards, center, spacing, axis)
    local count = #cards
    local axisX = axis and axis[1] or 1
    local axisZ = axis and axis[2] or 0

    for i, card in ipairs(cards) do
        card.setLock(false)
        local offset = (i - (count + 1) / 2) * spacing
        card.setPosition({
            center.x + axisX * offset,
            center.y + (i * 0.05),
            center.z + axisZ * offset
        }, false, false)
    end
end

function getCardSpreadWidth_TTSmobile(card, axis)
    local normalizedBounds = safeObjectCall_TTSmobile(card, "getBoundsNormalized", nil)
    local normalizedSize = normalizedBounds and normalizedBounds.size or nil
    if normalizedSize then
        local normalizedWidth = normalizedSize.x or normalizedSize[1] or 0
        if normalizedWidth >= 0.1 then
            return normalizedWidth
        end
    end

    local bounds = safeObjectCall_TTSmobile(card, "getBounds", nil)
    local size = bounds and bounds.size or nil
    if not size then
        return 2.4
    end
    local axisX = axis and axis[1] or 1
    local axisZ = axis and axis[2] or 0
    local width = math.abs((size.x or size[1] or 0) * axisX) + math.abs((size.z or size[3] or 0) * axisZ)
    if width < 0.1 then
        return 2.4
    end
    return width
end

function getCardSpreadOffsets_TTSmobile(cards, axis, spreadCards)
    local offsets = {}
    if not spreadCards then
        for i, _ in ipairs(cards) do
            offsets[i] = 0
        end
        return offsets
    end

    local widths = {}
    local totalWidth = 0
    for i, card in ipairs(cards) do
        widths[i] = getCardSpreadWidth_TTSmobile(card, axis)
        totalWidth = totalWidth + widths[i]
    end

    local leftEdge = -totalWidth / 2
    local cursor = leftEdge
    for i, width in ipairs(widths) do
        offsets[i] = cursor + width / 2
        cursor = cursor + width
    end
    return offsets
end

function placeCardsAtOrientedWorldPositionWithRotation_TTSmobile(cards, center, offsets, axis, yaw)
    local axisX = axis and axis[1] or 1
    local axisZ = axis and axis[2] or 0

    for i, card in ipairs(cards) do
        card.setLock(false)
        local offset = offsets and offsets[i] or 0
        card.setPosition({
            center.x + axisX * offset,
            center.y + (i * 0.05),
            center.z + axisZ * offset
        }, false, false)
        if yaw ~= nil then
            card.setRotationSmooth(getRotationWithYaw_TTSmobile(card, yaw), false, false)
        end
    end
end

function placeCardsAtOrientedWorldPositionNoRotation_TTSmobile(cards, center, spacing, axis)
    local count = #cards
    local axisX = axis and axis[1] or 1
    local axisZ = axis and axis[2] or 0

    for i, card in ipairs(cards) do
        card.setLock(false)
        local offset = (i - (count + 1) / 2) * spacing
        card.setPosition({
            center.x + axisX * offset,
            center.y + (i * 0.05),
            center.z + axisZ * offset
        }, false, false)
    end
end

function placeCardsInHandZone_TTSmobile(cards, handZone, yOffset)
    local zonePos = handZone.getPosition()
    local zoneRot = handZone.getRotation()
    local yaw = getYawFromRotation_TTSmobile(zoneRot, 0)
    local angle = math.rad(yaw)
    local count = #cards
    local spacing = 1.15

    for i, card in ipairs(cards) do
        card.setLock(false)
        local localX = (i - (count + 1) / 2) * spacing
        local worldX = zonePos.x + localX * math.cos(angle)
        local worldZ = zonePos.z - localX * math.sin(angle)
        dlog("Setze Karte " .. tostring(card.getGUID()) .. " auf x=" .. tostring(worldX) .. ", y=" .. tostring(zonePos.y + 1.0 + (yOffset or 0) + i * 0.03) .. ", z=" .. tostring(worldZ))
        card.setPosition({worldX, zonePos.y + 1.0 + (yOffset or 0) + i * 0.03, worldZ}, false, false)
        card.setRotationSmooth(getRotationWithYaw_TTSmobile(card, yaw), false, false)
    end
end


function placeCardsInHandTransform_TTSmobile(cards, handTransform, yOffset)
    local zonePos = handTransform.position
    local zoneRot = handTransform.rotation
    local yaw = getYawFromRotation_TTSmobile(zoneRot, 0)
    local angle = math.rad(yaw)
    local count = #cards
    local spacing = 1.15
    for i, card in ipairs(cards) do
        card.setLock(false)
        local localX = (i - (count + 1) / 2) * spacing
        local worldX = zonePos.x + localX * math.cos(angle)
        local worldZ = zonePos.z - localX * math.sin(angle)
        local worldY = zonePos.y + 1.0 + (yOffset or 0) + i * 0.03
        dlog(
            "Setze Karte " ..
            tostring(card.getGUID()) ..
            " in HandTransform auf x=" .. tostring(worldX) ..
            ", y=" .. tostring(worldY) ..
            ", z=" .. tostring(worldZ)
        )
        card.setPosition({worldX, worldY, worldZ}, false, false)
        card.setRotationSmooth(getRotationWithYaw_TTSmobile(card, yaw), false, false)
    end
end


function scanAndSendHand_TTSmobile(color, ausloeser)
    if not requirePythonServer_TTSmobile(ausloeser or "scanAndSendHand") then
        return
    end
    local handZone = getHandZoneForColor(color)
    if not handZone then
        return
    end
    local cardsData = {}
    local handObjects = getHandObjectsForColor_TTSmobile(color)
    for _, obj in ipairs(handObjects) do
        if obj and safeObjectTag_TTSmobile(obj) == "Card" then
            local ok, cardDataOrError = pcall(function()
            local data = safeObjectCall_TTSmobile(obj, "getData", {}) or {}
            local cardID = data and data.CardID or nil
            local deckID = cardID and math.floor(cardID / 100) or nil
            local cardIndex = cardID and (cardID % 100) or nil
            local customDeck = nil
            if data and data.CustomDeck and deckID then
              customDeck = data.CustomDeck[deckID] or data.CustomDeck[tostring(deckID)]
            end
            if not customDeck and data and data.CustomDeck then
              for __, v in pairs(data.CustomDeck) do
                customDeck = v
                break
              end
            end
            
            local guid = safeObjectCall_TTSmobile(obj, "getGUID", nil)
            if not guid then
                return nil
            end
            local flip = known_card_flips[guid]
            local faceDown = false
            if flip ~= nil then
                faceDown = flip
            else -- Fallback nur fuer Karten, die bereits verdeckt aufgenommen wurden
                faceDown = getActualFaceDown_TTSmobile(obj)
            end
            local objectName = safeObjectCall_TTSmobile(obj, "getName", "")
            local objectDescription = safeObjectCall_TTSmobile(obj, "getDescription", "")

            local cardData = {
                guid = guid,
                name = objectName ~= "" and objectName or nil,
                desc = objectDescription ~= "" and objectDescription or "",
                image = customDeck and customDeck.FaceURL or "",
                back_image = customDeck and customDeck.BackURL or "",
                builtin_deck = builtinDeck,
                card_index = cardIndex,
                atlas_width = customDeck and customDeck.NumWidth or 1,
                atlas_height = customDeck and customDeck.NumHeight or 1,
                face_down = faceDown,
                hide_when_face_down = data and data.HideWhenFaceDown or false,
                back_is_hidden = customDeck and customDeck.BackIsHidden or false,
                scale_x = data and data.Transform and data.Transform.scaleX or 1,
                scale_z = data and data.Transform and data.Transform.scaleZ or 1,
                sideways = data and data.SidewaysCard or false,
                attached_decals = data and data.AttachedDecals or nil,
                hand_sort_x = data and data.Transform and data.Transform.posX or 0,
                hand_sort_z = data and data.Transform and data.Transform.posZ or 0,
                hand_sort = handZone and getHandSortValue(obj, handZone) or 0,
            }
            return cardData
            end)
            local cardData = ok and cardDataOrError or nil
            if not ok then
                dlog("Karte beim Handscan uebersprungen: " .. tostring(cardDataOrError))
            end
            if cardData then
            if _==1 then 
                dlog("scanAndSendHand_TTSmobile CARD DEBUG: " .. JSON.encode(cardData))
            end

            if cardData.name==nil then
              if #cardData.desc>0 and #cardData.desc<=10 then
                cardData.name = cardData.desc -- sometimes the name is in the description instead
              else
                cardData.name = ""
              end
            end
            table.insert(cardsData, cardData)
            end
        end
    end
    
    table.sort(cardsData, function(a, b)
        return a.hand_sort < b.hand_sort
        -- return a.hand_sort > b.hand_sort
    end)
    
    local currentJson = JSON.encode(cardsData)
    if currentJson ~= last_sent_states[color] then
        last_sent_states[color] = currentJson
        sendHandToPython_TTSmobile(color, cardsData)
    end
end

function getHandZoneForColor(color)
    local handTransform = getHandTransformForColor_TTSmobile(color)
    if not handTransform or not handTransform.position then
        return nil
    end
    return {
        getPosition = function()
            return handTransform.position
        end,
        getRotation = function()
            return handTransform.rotation or {x = 0, y = 0, z = 0}
        end,
        handTransform = handTransform
    }
end

function colorHasHandZone_TTSmobile(color)
    return getHandTransformForColor_TTSmobile(color) ~= nil
end

function getHandZoneColors_TTSmobile()
    local colors = {}
    for _, color in ipairs(TRACKED_COLORS) do
        if isValidPlayerColor_TTSmobile(color) and colorHasHandZone_TTSmobile(color) then
            table.insert(colors, color)
        end
    end
    dlog("getHandZoneColors_TTSmobile: found hand zone colors: " .. table.concat(colors, ", "))
    return colors
end

function getSeatedColors_TTSmobile()
    local colors = {}
    for _, color in ipairs(TRACKED_COLORS) do
        local player = safeGetPlayer_TTSmobile(color)
        local seated = safeCall_TTSmobile("Player.seated " .. tostring(color), false, function()
            return player and player.seated == true
        end)
        if seated then
            table.insert(colors, color)
        end
    end
    dlog("getSeatedColors_TTSmobile: found seated colors: " .. table.concat(colors, ", "))
    return colors
end

function getHandSortValue(card, handZone)
    local cardPos = safeObjectCall_TTSmobile(card, "getPosition", nil)
    local zonePos = safeObjectCall_TTSmobile(handZone, "getPosition", nil)
    local zoneRot = safeObjectCall_TTSmobile(handZone, "getRotation", nil)
    if not cardPos or not zonePos or not zoneRot then
        return 0
    end
    local dx = cardPos.x - zonePos.x
    local dz = cardPos.z - zonePos.z
    local angle = math.rad(zoneRot.y)
    -- lokale X-Achse der Handzone
    local localX = dx * math.cos(angle) - dz * math.sin(angle)
    return localX
end

function scanAndSendAllHands_TTSmobile(ausloeser)
    if not requirePythonServer_TTSmobile(ausloeser or "scanAndSendAllHands") then
        return
    end
    for _, color in ipairs(TRACKED_COLORS) do
        scanAndSendHand_TTSmobile(color, ausloeser)
    end
end


function isValidPlayerColor_TTSmobile(color)
    if not color then
        return false
    end
    for _, availableColor in ipairs(TRACKED_COLORS) do
        if availableColor == color then
            return true
        end
    end
    return false
end


function parseTag_TTSmobile(tag, tagName, context) -- parse tag for colour (and name in tag for snap points)
    tagName = tagName or "TTSmobile"
    if not tag then
        if context == "button" then
            return {
                key = "",
                name = "",
                allowed_colors = nil,
            }
        end
        return nil
    end
    if tag == "TTSmobileHideButtons" then
        return {
            key = tag,
            name = "",
            allowed_colors = false,
        }
    end

    local prefix = tagName
    if string.sub(prefix, -1) ~= "_" then
        prefix = prefix .. "_"
    end

    local payload = string.match(tag, "^" .. prefix .. "(.+)$")
    if not payload then
        if context == "button" then
            return {
                key = "",
                name = "",
                allowed_colors = nil,
            }
        end
        return nil
    end

    local rawName = payload
    local rawColors = nil
    local markerStart, markerEnd = string.find(payload, "_For_", 1, true)
    if markerStart then
        rawName = string.sub(payload, 1, markerStart - 1)
        rawColors = string.sub(payload, markerEnd + 1)
    elseif string.sub(payload, 1, 4) == "For_" then
        rawName = ""
        rawColors = string.sub(payload, 5)
    end

    local allowedColors = nil
    if rawColors and rawColors ~= "" then
        allowedColors = {}
        for color in string.gmatch(rawColors, "([^_]+)") do
            if isValidPlayerColor_TTSmobile(color) then
                table.insert(allowedColors, color)
            else
                log(tagName .. " Tag enthaelt ungueltige Spielerfarbe: " .. tostring(color) .. " in " .. tostring(tag))
            end
        end
    end
    return {
        key = payload,
        name = string.gsub(rawName, "_", " "),
        allowed_colors = allowedColors,
    }
end

function getMobileButtonAllowedColors_TTSmobile(obj)
    if not obj then
        return nil
    end

    for _, tag in ipairs(safeObjectCall_TTSmobile(obj, "getTags", {}) or {}) do
        local parsed = parseTag_TTSmobile(tag, "TTSmobile", "button")
        if parsed and parsed.allowed_colors == false then
            return false
        end
        if parsed and parsed.allowed_colors then
            return parsed.allowed_colors
        end
    end

    return nil
end

function getMobileDropTargetsFromSnapTags_TTSmobile(tags)
    local targets = {}
    if not tags then
        return targets
    end
    for _, tag in ipairs(tags) do
        local target = parseTag_TTSmobile(tag, "TTSmobile", "snap")
        if target and target.allowed_colors ~= false then
            table.insert(targets, target)
        end
    end
    return targets
end

function getDropTargetDedupeKey_TTSmobile(key, description)
    return tostring(key or "") .. "__" .. tostring(description or "")
end

function insertDropTargetIfNew_TTSmobile(targets, seenDropZoneKeys, key, description, targetData)
    local dedupeKey = getDropTargetDedupeKey_TTSmobile(key, description)
    if not key or seenDropZoneKeys[dedupeKey] then
        return
    end
    seenDropZoneKeys[dedupeKey] = true
    table.insert(targets, targetData)
end

function scanDropZones_TTSmobile()
    local targets = {}
    local seenDropZoneKeys = {}
    -- Freie Snap Points auf dem Tisch / in der Welt
    local globalSnapPoints = safeCall_TTSmobile("Global.getSnapPoints", {}, function()
        return Global.getSnapPoints() or {}
    end)
    for snapIndex, snap in ipairs(globalSnapPoints) do
        local snapTargets = getMobileDropTargetsFromSnapTags_TTSmobile(snap.tags)

        for _, target in ipairs(snapTargets) do
            insertDropTargetIfNew_TTSmobile(targets, seenDropZoneKeys, target.key, "", {
                type = "global_snap",
                snap_index = snapIndex,
                name = target.name,
                allowed_colors = target.allowed_colors,
            })
        end
    end
    -- Snap Points auf Objekten
    for _, obj in ipairs(safeGetAllObjects_TTSmobile()) do
        if obj then
            local snapPoints = safeObjectCall_TTSmobile(obj, "getSnapPoints", {}) or {}
            local description = trimString_TTSmobile(safeObjectCall_TTSmobile(obj, "getDescription", ""))

            for snapIndex, snap in ipairs(snapPoints) do
                local snapTargets = getMobileDropTargetsFromSnapTags_TTSmobile(snap.tags)

                for _, target in ipairs(snapTargets) do
                    local objectGuid = safeObjectCall_TTSmobile(obj, "getGUID", nil)
                    if objectGuid then
                        local targetData = {
                            type = "object_snap",
                            object_guid = objectGuid,
                            snap_index = snapIndex,
                            name = target.name,
                            allowed_colors = target.allowed_colors,
                        }
                        if description ~= "" then
                            targetData.description = description
                        end
                        insertDropTargetIfNew_TTSmobile(targets, seenDropZoneKeys, target.key, description, targetData)
                    end
                end
            end
        end
    end
    table.sort(targets, function(a, b)
        return tostring(a.name) < tostring(b.name)
    end)
    return targets
end

function trimString_TTSmobile(value)
    if value == nil then
        return ""
    end
    local text = tostring(value)
    text = string.gsub(text, "^%s+", "")
    text = string.gsub(text, "%s+$", "")
    return text
end

function getMobileButtonDisplayName_TTSmobile(obj, button, buttonCount)
    local label = trimString_TTSmobile(button and button.label or "")
    if label ~= "" then
        return label
    end
    if buttonCount == 1 and obj then
        return trimString_TTSmobile(safeObjectCall_TTSmobile(obj, "getName", ""))
    end
    return ""
end

function getMobileButtonTooltip_TTSmobile(obj, button, buttonCount)
    local tooltip = trimString_TTSmobile(button and button.tooltip or "")
    if tooltip ~= "" then
        return tooltip
    end

    if buttonCount == 1 and obj then
        local name = trimString_TTSmobile(safeObjectCall_TTSmobile(obj, "getName", ""))
        if name ~= "" then
            return trimString_TTSmobile(safeObjectCall_TTSmobile(obj, "getDescription", ""))
        end
    end

    return ""
end

function getMobileButtonId_TTSmobile(objectGuid, clickFunction)
    return tostring(objectGuid) .. ":" .. tostring(clickFunction)
end

function getMobileButtonDedupeKey_TTSmobile(name, tooltip, allowedColors)
    local colorKey = "ALL"
    if type(allowedColors) == "table" then
        local colors = {}
        for _, color in ipairs(allowedColors) do
            table.insert(colors, tostring(color))
        end
        table.sort(colors)
        colorKey = table.concat(colors, "_")
    end
    return tostring(name) .. "__" .. tostring(tooltip or "") .. "__" .. colorKey
end

function isLuaIdentifier_TTSmobile(value)
    return string.match(tostring(value or ""), "^[A-Za-z_][A-Za-z0-9_]*$") ~= nil
end

function getFunctionOwnerData_TTSmobile(button, fallbackObj)
    local owner = safeCall_TTSmobile("button.function_owner", nil, function()
        return button and button.function_owner or nil
    end)
    if not owner then
        owner = fallbackObj
    end

    if owner == Global then
        return "global", nil
    end

    local ownerGuid = safeObjectCall_TTSmobile(owner, "getGUID", nil)
    if ownerGuid then
        if ownerGuid == "-1" then
            return "global", nil
        end
        return "object", ownerGuid
    end

    return "object", fallbackObj and safeObjectCall_TTSmobile(fallbackObj, "getGUID", nil) or nil
end

function scanMobileButtons_TTSmobile()
    local mobileButtons = {}
    local seenActions = {}

    for _, obj in ipairs(safeGetAllObjects_TTSmobile()) do
        if obj then
            local objectGuid = safeObjectCall_TTSmobile(obj, "getGUID", nil)
            local buttons = safeObjectCall_TTSmobile(obj, "getButtons", {}) or {}
            local buttonCount = #buttons
            local allowedColors = getMobileButtonAllowedColors_TTSmobile(obj)

            if allowedColors ~= false then
                for _, button in ipairs(buttons) do
                    local name = getMobileButtonDisplayName_TTSmobile(obj, button, buttonCount)
                    local tooltip = getMobileButtonTooltip_TTSmobile(obj, button, buttonCount)
                    local clickFunction = trimString_TTSmobile(button.click_function)
                    local actionKey = getMobileButtonId_TTSmobile(objectGuid, clickFunction)
                    local dedupeKey = getMobileButtonDedupeKey_TTSmobile(name, tooltip, allowedColors)
                    if objectGuid and name ~= "" and not seenActions[dedupeKey] then
                        if clickFunction ~= "" and isLuaIdentifier_TTSmobile(clickFunction) then
                            local ownerType, ownerGuid = getFunctionOwnerData_TTSmobile(button, obj)
                            seenActions[dedupeKey] = true
                            table.insert(mobileButtons, {
                                id = actionKey,
                                object_guid = objectGuid,
                                function_owner_type = ownerType,
                                function_owner_guid = ownerGuid,
                                name = name,
                                tooltip = tooltip,
                                click_function = clickFunction,
                                allowed_colors = allowedColors,
                            })
                        end
                    end
                end
            end
        end
    end

    table.sort(mobileButtons, function(a, b)
        return tostring(a.name) < tostring(b.name)
    end)
    return mobileButtons
end

function scheduleDropZoneScan_TTSmobile(reason, delay)
    if not requirePythonServer_TTSmobile(reason or "Drop-Zonen-Scan") then
        return
    end
    delay = delay or 0.5
    if pending_drop_zone_scan then
        return
    end
    pending_drop_zone_scan = true
    Wait.time(function()
        pending_drop_zone_scan = false
        scanAndSendDropZonesIfChanged_TTSmobile(reason .. " delayed")
    end, delay)
end

function scheduleMobileButtonScan_TTSmobile(reason, delay)
    if not requirePythonServer_TTSmobile(reason or "Mobile-Button-Scan") then
        return
    end
    delay = delay or 0.5
    if pending_mobile_button_scan then
        return
    end
    pending_mobile_button_scan = true
    Wait.time(function()
        pending_mobile_button_scan = false
        scanAndSendMobileButtonsIfChanged_TTSmobile(reason .. " delayed")
    end, delay)
end

function scanAndSendDropZonesIfChanged_TTSmobile(reason)
    if not requirePythonServer_TTSmobile(reason or "Drop-Zonen-Scan") then
        return
    end
    local ok, dropZonesOrError = pcall(function()
        return scanDropZones_TTSmobile()
    end)
    if not ok then
        log("Mobile Companion Drop-Zonen-Scan fehlgeschlagen: " .. tostring(dropZonesOrError))
        return
    end
    local dropZones = dropZonesOrError
    local currentJson = JSON.encode(dropZones)
    if currentJson == last_sent_drop_zones_json then
        return
    end
    last_sent_drop_zones_json = currentJson
    sendDropZonesToPython_TTSmobile(dropZones)
end

function scanAndSendMobileButtonsIfChanged_TTSmobile(reason)
    if not requirePythonServer_TTSmobile(reason or "Mobile-Button-Scan") then
        return
    end
    local ok, mobileButtonsOrError = pcall(function()
        return scanMobileButtons_TTSmobile()
    end)
    if not ok then
        log("Mobile Companion Button-Scan fehlgeschlagen: " .. tostring(mobileButtonsOrError))
        return
    end
    local mobileButtons = mobileButtonsOrError
    local currentJson = JSON.encode(mobileButtons)
    if currentJson == last_sent_mobile_buttons_json then
        return
    end
    last_sent_mobile_buttons_json = currentJson
    sendMobileButtonsToPython_TTSmobile(mobileButtons)
end

function sendDropZonesToPython_TTSmobile(dropZones)
    if not requirePythonServer_TTSmobile("Drop-Zonen senden") then
        return
    end
    WebRequest.post(
        SERVER_URLS["update_drop_zones"],
        JSON.encode({
            drop_zones = dropZones,
            hand_zone_colors = getHandZoneColors_TTSmobile(),
            seated_colors = getSeatedColors_TTSmobile()
        }),
        function(request)
            handlePythonServerRequestResult_TTSmobile(request, "Senden der Drop-Zonen an Python")
        end
    )
end

function sendMobileButtonsToPython_TTSmobile(mobileButtons)
    if not requirePythonServer_TTSmobile("Mobile-Buttons senden") then
        return
    end
    WebRequest.post(
        SERVER_URLS["update_mobile_buttons"],
        JSON.encode({
            mobile_buttons = mobileButtons,
            hand_zone_colors = getHandZoneColors_TTSmobile(),
            seated_colors = getSeatedColors_TTSmobile()
        }),
        function(request)
            handlePythonServerRequestResult_TTSmobile(request, "Senden der Mobile-Buttons an Python")
        end
    )
end


function sendHandToPython_TTSmobile(playerColor, cardsList)
    if not requirePythonServer_TTSmobile("Handdaten senden") then
        return
    end
    local dropZones = safeCall_TTSmobile("scanDropZones fuer Hand-Sync", {}, function()
        return scanDropZones_TTSmobile()
    end)
    local mobileButtons = safeCall_TTSmobile("scanMobileButtons fuer Hand-Sync", {}, function()
        return scanMobileButtons_TTSmobile()
    end)
    WebRequest.post(
        SERVER_URLS["update_hand"],
        JSON.encode({
            color = playerColor,
            cards = cardsList,
            drop_zones = dropZones,
            mobile_buttons = mobileButtons,
            hand_zone_colors = getHandZoneColors_TTSmobile(),
            seated_colors = getSeatedColors_TTSmobile()
        }),
        function(request)
            handlePythonServerRequestResult_TTSmobile(request, "Senden der Handdaten an Python")
        end
    )
end
