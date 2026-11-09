
-- lua script fuer Tabletop Simulator 

-- scripting API: https://api.tabletopsimulator.com/intro/

-- object.lua direkt im Workshop-Objekt

-- debug.traceback does not work unfortunately and the games error message also does not mention the line of error..

-- ingame in TTS brauchen Snap Points die als Ablageort fuer Karten erkannt werden sollen den Tag: "TTSmobile_Abwurfstapel" usw.
-- wenn ein Stapel nur fuer eine bestimmte Farbe ist, dann diese mit reinschreiben zb. TTSmobile_Abwurfstapel_For_Yellow_Blue_Red
-- und fuer Buttons die nur fuer bestimmte Farben angezeigt werden muss das beinhaltene Objekt den Tag TTSmobile_For_Yellow usw. 
-- falls fuer ein Objekt keine Buttons im Handy angezeigt werden sollen, kann der Tag TTSmobileHideButtons verwendet werden

local DEBUG = false
local SERVER_URL = "http://127.0.0.1:5001"
local TRACKED_COLORS = {}
local helper_instance
local sync_run
local snapshot_ready = false
local snapshot_pending = false
local heartbeat_pending = false
local pending_hand_scans = {}
local pending_table_scan = false
local streams = {}
local seen_actions = {}

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

local function postPayload(path, data, callback)
    local finished = false
    local timeout
    local request = WebRequest.post(SERVER_URL .. path, {payload = JSON.encode(data)}, function(response)
        if finished then
            return
        end
        finished = true
        if timeout then
            Wait.stop(timeout)
        end
        local code = response and response.response_code or 0
        callback(response ~= nil and not response.is_error and code >= 200 and code < 300, response, code)
    end)
    if not finished then
        timeout = Wait.time(function()
            finished = true
            if request then
                request.dispose()
            end
            callback(false, nil, 0)
        end, 6)
    end
end

local function requirePythonServer_TTSmobile()
    return snapshot_ready
end

local function requestHeartbeat()
    if heartbeat_pending then
        return
    end
    heartbeat_pending = true
    postPayload("/health", {helper = helper_instance}, function(ok, response)
        heartbeat_pending = false
        if not ok then
            snapshot_ready = false
            return
        end
        local decoded, status = pcall(JSON.decode, response.text)
        if not decoded or type(status) ~= "table" or type(status.run) ~= "string" then
            snapshot_ready = false
            return
        end
        if sync_run ~= status.run then
            sync_run = status.run
            snapshot_ready = false
            snapshot_pending = false
            streams = {}
            seen_actions = {}
        end
        if status.ready then
            local recovered = not snapshot_ready
            snapshot_ready = true
            if recovered then
                scanAndSendAllHands_TTSmobile("Heartbeat")
                scheduleTableScan_TTSmobile("Heartbeat", 0.1)
            end
            for stream, state in pairs(streams) do
                if state.retry then
                    state.retry = false
                    if stream == "table" then
                        scheduleTableScan_TTSmobile("Retry", 0.1)
                    elseif stream ~= "snapshot" then
                        scheduleHandScan_TTSmobile(stream, "Retry", 0.1, state.force)
                    end
                end
            end
        elseif not snapshot_ready then
            syncSnapshot_TTSmobile()
        end
    end)
end

function onLoad(save_state)
    TRACKED_COLORS = {}
    for _, color in ipairs(Player.getAvailableColors()) do
        if color ~= "Grey" then
            table.insert(TRACKED_COLORS, color)
        end
    end
    helper_instance = self.getGUID() .. ":" .. string.format("%09d%09d", math.random(1, 999999999), math.random(1, 999999999))
    Wait.time(requestHeartbeat, 0.2)
    Wait.time(requestHeartbeat, 3, -1)
end

function scheduleHandScan_TTSmobile(color, reason, delay, force)
    if not color or not snapshot_ready then
        return
    end
    local pending = pending_hand_scans[color]
    if pending then
        pending.force = pending.force or force
        return
    end
    pending = {force = force}
    pending_hand_scans[color] = pending
    Wait.time(function()
        pending_hand_scans[color] = nil
        scanAndSendHand_TTSmobile(color, reason, pending.force)
    end, delay or 0.1)
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
    scheduleTableScan_TTSmobile("Objekt gedroppt", 0.5)
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
    scheduleTableScan_TTSmobile("Objekt gespawnt", 0.5)
end

function onObjectDestroy(object)
    if not requirePythonServer_TTSmobile("onObjectDestroy") then
        return
    end
    scheduleTableScan_TTSmobile("Objekt geloescht", 0.5)
end

function onObjectStateChange(object, old_guid)
    if not requirePythonServer_TTSmobile("onObjectStateChange") then
        return
    end
    scheduleTableScan_TTSmobile("Objektzustand geaendert", 0.5)
end

function onObjectEnterZone(zone, object)
    if not requirePythonServer_TTSmobile("onObjectEnterZone") then
        return
    end
    dlog("onObjectEnterZone")
    if zone and safeObjectTag_TTSmobile(zone) == "Hand" and object and safeObjectTag_TTSmobile(object) == "Card" then
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
    if not snapshot_ready or type(data) ~= "table" or data.helper ~= helper_instance or data.run ~= sync_run then
        return
    end
    if data.action == "card_action" then
        local ok, guids = pcall(JSON.decode, data.guids_json or "")
        handleCardAction_TTSmobile(data, ok and guids or nil)
    elseif data.action == "request_hand_sync" and type(data.colors) == "table" then
        for _, color in ipairs(data.colors) do
            if isValidPlayerColor_TTSmobile(color) then
                scheduleHandScan_TTSmobile(color, "request_hand_sync", 0.1, data.force == true)
            end
        end
        scheduleTableScan_TTSmobile("request_hand_sync", 0.1, data.force == true)
    end
end

function getActualFaceDown_TTSmobile(card)
    if not card then
        return false
    end
    if type(card.is_face_down) == "boolean" then
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
    if snapshot_ready and flip ~= old_flip and object and safeObjectTag_TTSmobile(object) == "Card" then
        local color = getColorForCardInHand_TTSmobile(object)
        scheduleHandScan_TTSmobile(color, "card rotation", 0.25)
    end
end

function flipCardsFromMobile_TTSmobile(color, cards)
    for _, card in ipairs(cards) do
        card.flip()
    end
    return true
end

local function liveHandCards(color)
    local cards = {}
    for _, card in ipairs(getHandObjectsForColor_TTSmobile(color)) do
        if safeObjectTag_TTSmobile(card) == "Card" then
            local guid = safeObjectCall_TTSmobile(card, "getGUID", nil)
            if guid then
                cards[guid] = card
            end
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

local function sendActionResult(data, result, error_key)
    postPayload("/action_result", {
        helper = helper_instance, run = data.run, action_id = data.action_id,
        result = result, error_key = error_key,
    }, function(ok)
        if not ok then
            dlog("Could not deliver action result " .. tostring(data.action_id))
        end
    end)
end

local function actionApplied(data, guids, expectedFlips)
    local source = liveHandCards(data.color)
    if data.card_action == "reorder_hand" then
        local zone = getHandZoneForColor(data.color)
        if not zone then
            return false
        end
        local ordered = {}
        for guid, card in pairs(source) do
            table.insert(ordered, {guid = guid, position = getHandSortValue(card, zone)})
        end
        table.sort(ordered, function(a, b) return a.position < b.position end)
        if #ordered ~= #guids then
            return false
        end
        for i, guid in ipairs(guids) do
            if ordered[i].guid ~= guid then
                return false
            end
        end
        return true
    end

    local destination = data.card_action == "give_to_player" and liveHandCards(data.target) or nil
    for _, guid in ipairs(guids) do
        if expectedFlips then
            if not source[guid] or getActualFaceDown_TTSmobile(source[guid]) ~= expectedFlips[guid] then
                return false
            end
        elseif source[guid] or (destination and not destination[guid]) then
            return false
        end
    end
    return true
end

function handleCardAction_TTSmobile(data, guids)
    if type(data.action_id) ~= "string" or seen_actions[data.action_id] then
        return
    end
    local runActions = seen_actions
    runActions[data.action_id] = true
    Wait.time(function() runActions[data.action_id] = nil end, 30)

    local handler = getActionHandlers_TTSmobile()[data.card_action]
    if not handler or not isValidPlayerColor_TTSmobile(data.color) or type(guids) ~= "table" or #guids == 0 then
        sendActionResult(data, "rejected", "errors.action_failed")
        return
    end
    local liveCards = liveHandCards(data.color)
    local cards, used = {}, {}
    local expectedFlips = data.card_action == "flip_cards" and {} or nil
    for _, guid in ipairs(guids) do
        local card = liveCards[guid]
        if not card or used[guid] then
            sendActionResult(data, "rejected", "errors.card_not_in_current_hand")
            return
        end
        used[guid] = true
        table.insert(cards, card)
        if expectedFlips then
            expectedFlips[guid] = not getActualFaceDown_TTSmobile(card)
        end
    end
    if data.card_action == "reorder_hand" then
        for guid in pairs(liveCards) do
            if not used[guid] then
                sendActionResult(data, "rejected", "errors.hand_order_changed")
                return
            end
        end
    end

    local function complete(result, error_key)
        if sync_run ~= data.run then
            return
        end
        if result ~= "rejected" then
            scheduleHandScan_TTSmobile(data.color, "card action", 0.1, result == "uncertain")
            if data.card_action == "give_to_player" then
                scheduleHandScan_TTSmobile(data.target, "card action", 0.1, result == "uncertain")
            end
            scheduleTableScan_TTSmobile("card action", 0.5)
        end
        sendActionResult(data, result, error_key)
    end

    local called, accepted, error_key = pcall(handler, data.color, cards, guids, data.target)
    if not called then
        log("Mobile Helper action failed: " .. tostring(accepted))
        complete("uncertain")
    elseif not accepted then
        complete("rejected", error_key)
    else
        Wait.condition(
            function() complete("ok") end,
            function() return actionApplied(data, guids, expectedFlips) end,
            4,
            function() complete("uncertain") end
        )
    end
end

function playCardsToTable_TTSmobile(color, cards)
    if not getHandTransformForColor_TTSmobile(color) then
        return false, "errors.invalid_player_color"
    end
    placeCardsInFrontOfHandZone_TTSmobile(color, cards)
    return true
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

local function sameSnapPosition(a, b)
    return a and b
        and math.abs(a.x - b.x) < 0.001
        and math.abs(a.y - b.y) < 0.001
        and math.abs(a.z - b.z) < 0.001
end

local function snapHasTarget(snap, target, color)
    if not snap or not sameSnapPosition(snap.position, target.position) then
        return false
    end
    for _, tagged in ipairs(getMobileDropTargetsFromSnapTags_TTSmobile(snap.tags)) do
        if tagged.key == target.tag_key then
            if tagged.allowed_colors == nil then
                return true
            end
            for _, allowed in ipairs(tagged.allowed_colors) do
                if allowed == color then
                    return true
                end
            end
        end
    end
    return false
end

function playCardsToDropZone_TTSmobile(color, cards, guids, targetJson)
    local ok, target = pcall(JSON.decode, targetJson or "")
    if not ok or type(target) ~= "table" then
        return false, "errors.drop_target_changed"
    end

    local obj, snap
    if target.type == "global_snap" then
        snap = (Global.getSnapPoints() or {})[target.snap_index]
    elseif target.type == "object_snap" then
        obj = getObjectFromGUID(target.object_guid)
        if obj then
            snap = (obj.getSnapPoints() or {})[target.snap_index]
        end
    end
    if not snapHasTarget(snap, target, color) then
        return false, "errors.drop_target_changed"
    end

    local pos = obj and obj.positionToWorld(snap.position) or snap.position
    local yaw = getYawFromRotation_TTSmobile(snap.rotation, obj and 0 or 180)
    if obj then
        yaw = yaw + getYawFromRotation_TTSmobile(obj.getRotation(), 0)
    end
    placeCardsOnDropTarget_TTSmobile(cards, pos, yaw, target.spread_cards == true)
    return true
end

function giveCardsToPlayer_TTSmobile(sourceColor, cards, guids, targetColor)
    local handTransform = getHandTransformForColor_TTSmobile(targetColor)
    if not handTransform then
        return false, "errors.invalid_target_player"
    end
    placeCardsInHandTransform_TTSmobile(cards, handTransform, 0)
    return true
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
    return true
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


function collectHand_TTSmobile(color)
    local handZone = getHandZoneForColor(color)
    if not handZone then
        return {}
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
                face_down = getActualFaceDown_TTSmobile(obj),
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
    
    return cardsData
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
                tag_key = target.key,
                position = {x = snap.position.x, y = snap.position.y, z = snap.position.z},
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

function scheduleTableScan_TTSmobile(reason, delay, force)
    if not snapshot_ready then
        return
    end
    if pending_table_scan then
        pending_table_scan.force = pending_table_scan.force or force
        return
    end
    local pending = {force = force}
    pending_table_scan = pending
    Wait.time(function()
        pending_table_scan = false
        if snapshot_ready then
            sendTableMetadata_TTSmobile(pending.force)
        end
    end, delay or 0.5)
end

function onPlayerChangeColor()
    scheduleTableScan_TTSmobile("seat change")
end

function onPlayerConnect()
    scheduleTableScan_TTSmobile("player joined")
end

function onPlayerDisconnect()
    scheduleTableScan_TTSmobile("player left")
end

local function collectTableMetadata()
    return {
        drop_zones = scanDropZones_TTSmobile(),
        mobile_buttons = scanMobileButtons_TTSmobile(),
        hand_zone_colors = getHandZoneColors_TTSmobile(),
        seated_colors = getSeatedColors_TTSmobile(),
    }
end

local function sendUpdate(path, stream, data, fingerprint, force, callback)
    local state = streams[stream] or {sequence = 0}
    streams[stream] = state
    if not force and (state.in_flight == fingerprint or (state.in_flight == nil and state.sent == fingerprint)) then
        return
    end
    state.sequence = state.sequence + 1
    state.in_flight = fingerprint
    local sequence, run = state.sequence, sync_run
    data.helper, data.run, data.sequence = helper_instance, run, sequence
    postPayload(path, data, function(ok, _, code)
        if sync_run ~= run or state.sequence ~= sequence then
            return
        end
        state.in_flight = nil
        if ok then
            state.sent = fingerprint
            state.retry = false
        elseif code == 409 then
            snapshot_ready = false
        elseif code == 0 or code >= 500 then
            state.retry, state.force = true, force
        else
            log("Mobile Helper update rejected: " .. path .. " (" .. tostring(code) .. ")")
        end
        if callback then
            callback(ok)
        end
    end)
end

function sendTableMetadata_TTSmobile(force)
    local ok, data = pcall(collectTableMetadata)
    if ok then
        sendUpdate("/update_table", "table", data, JSON.encode(data), force)
    else
        log("Mobile Helper table scan failed: " .. tostring(data))
    end
end

function syncSnapshot_TTSmobile()
    if snapshot_pending then
        return
    end
    local ok, snapshot = pcall(collectTableMetadata)
    if not ok then
        log("Mobile Helper snapshot failed: " .. tostring(snapshot))
        return
    end
    local metadata = JSON.encode(snapshot)
    snapshot.hands = {}
    local handFingerprints = {}
    for _, color in ipairs(TRACKED_COLORS) do
        local cards = collectHand_TTSmobile(color)
        snapshot.hands[color] = cards
        handFingerprints[color] = JSON.encode(cards)
    end
    snapshot_pending = true
    sendUpdate("/sync_snapshot", "snapshot", snapshot, "", true, function(success)
        snapshot_pending = false
        if success and not snapshot_ready then
            snapshot_ready = true
            streams.table = {sequence = 0, sent = metadata}
            for color, fingerprint in pairs(handFingerprints) do
                streams[color] = {sequence = 0, sent = fingerprint}
            end
            -- Re-read changes that took place while the snapshot was in flight.
            scanAndSendAllHands_TTSmobile("snapshot complete")
            scheduleTableScan_TTSmobile("snapshot complete", 0.1)
        end
    end)
end

function scanAndSendHand_TTSmobile(color, reason, force)
    if not snapshot_ready then
        return
    end
    local cards = collectHand_TTSmobile(color)
    sendUpdate("/update_hand", color, {color = color, cards = cards, force = force == true}, JSON.encode(cards), force)
    scheduleTableScan_TTSmobile(reason, 0.5)
end
