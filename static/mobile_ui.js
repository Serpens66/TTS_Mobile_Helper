const I18N = JSON.parse(document.getElementById('mobile-ui-i18n').textContent);
function t(key, params = {}) {
    let text = I18N[key] || key;
    for (const [name, value] of Object.entries(params || {})) {
        text = text.replaceAll(`{${name}}`, String(value));
    }
    return text;
}

function localizedMessage(data, field = 'message', fallbackKey = '') {
    const key = data?.[`${field}_key`] || fallbackKey;
    const params = data?.[`${field}_params`] || {};
    if (key) return t(key, params);
    return data?.[field] || '';
}

const urlParams = new URLSearchParams(window.location.search);
const CLIENT_ID_STORAGE_KEY = 'tts_mobile_companion_client_id';
const ADMIN_COLOR_STORAGE_KEY = 'tts_mobile_companion_admin_color';
let clientId = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
if (!clientId) {
    clientId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, clientId);
}
const isAdmin = urlParams.get('admin') === '1';
const colorMap = { Red: '#ff4d4d', Blue: '#00a8ff', Green: '#2ed573', Yellow: '#ffa502', White: '#eeeeee', Brown: '#8b5a2b', Orange: '#ff9f43', Teal: '#00d2d3', Purple: '#a55eea', Pink: '#ff6bcb' };
const defaultPlayerColors = Object.keys(colorMap);
let myColor = urlParams.get('color') || localStorage.getItem(ADMIN_COLOR_STORAGE_KEY) || defaultPlayerColors[0] || 'Red';
const TTS_CARD_BASE_WIDTH = 140;
const TTS_CARD_BASE_HEIGHT = 196;
const DECAL_POSITION_FACTOR_X = 50;
const DECAL_POSITION_FACTOR_Y = 50;
const DECAL_SIZE_FACTOR_X = 75;
const DECAL_SIZE_FACTOR_Y = 75;
const DECAL_ROTATION_OFFSET = 180;
const LONG_PRESS_MS = 500;
const DRAG_THRESHOLD_PX = 12;
const VIEW_MODE_STORAGE_KEY = 'tts_mobile_companion_view_mode';
const DRAG_MODE_STORAGE_KEY = 'tts_mobile_companion_drag_mode';
const PLAYER_FILTER_STORAGE_KEY = 'tts_mobile_companion_player_filter';
const FAVORITE_STORAGE_PREFIX = 'tts_mobile_companion_favorite';
const CARD_VERTICAL_CHROME_PX = 24;
const CARD_LAYOUT_RESERVE_PX = 8;
const MIN_RESPONSIVE_CARD_IMAGE_HEIGHT = 40;

let currentCards = [];
let playerColors = [];
let handZoneColors = [];
let seatedColors = [];
let handZoneColorsReceived = false;
let seatedColorsReceived = false;
let occupiedColors = [];
let dropZones = [];
let mobileButtons = [];
let pythonSocketConnected = false;
let luaConnected = false;
let luaLastContactAt = null;
let incomingInteractions = [];
let outgoingInteractions = [];
let activeOpenPick = null;
let openPickSelectedGuids = new Set();
let giveTargetColor = "";
let interactionTargetColor = "";
let selectedGuids = new Set();
let pressTimer = null;
let pressStart = null;
let draggingGuid = null;
let dragStarted = false;
let dragGuids = [];
let scrollbarDragging = false;
let scrollbarDragOffsetX = null;
let headerScrollDragging = false;
let headerScrollMoved = false;
let headerScrollStart = null;
let cardZoomGuid = null;
let cardZoomDragStart = null;
let cardZoomDragging = false;
let cardZoomDragMoved = false;
let actionMenuAllCards = false;
let mobileButtonAltClick = false;
let dropZoneSpreadCards = false;
let activeMenuMode = 'execute';
let activeFavoriteSlot = null;
let favoritePress = null;

updateControlledColorChrome();

const socket = io();
const container = document.getElementById('cards');
const headerContent = document.querySelector('.header-content');
const handScrollbar = document.getElementById('hand-scrollbar');
const handScrollbarThumb = document.getElementById('hand-scrollbar-thumb');
const selectionInfo = document.getElementById('selection-info');
const statusIndicator = document.getElementById('status-text');
const handCountButton = document.getElementById('hand-count');
const handCountNumber = document.getElementById('hand-count-number');
const colorButton = document.getElementById('color-button');
const colorDropdown = document.getElementById('color-dropdown');
const menu = document.getElementById('action-menu');
const buttonMenu = document.getElementById('button-menu');
const favoriteMenu = document.getElementById('favorite-menu');
const interactionMenu = document.getElementById('interaction-menu');
const openPickMenu = document.getElementById('open-pick-menu');
const cardZoomMenu = document.getElementById('card-zoom-menu');
const cardZoomCard = document.getElementById('card-zoom-card');
const settingsMenu = document.getElementById('settings-menu');
const backdrop = document.getElementById('menu-backdrop');
const fullscreenButton = document.getElementById('fullscreen-button');
const interactionButton = document.getElementById('interaction-button');
const mobileButtonsButton = document.getElementById('mobile-buttons-button');
const actionAllToggle = document.getElementById('action-all-toggle');
const actionZoneLayoutButton = document.getElementById('action-zone-layout');
const favoriteLeftButton = document.getElementById('favorite-left');
const favoriteRightButton = document.getElementById('favorite-right');

function setText(selector, key, params = {}) {
    const element = document.querySelector(selector);
    if (element) element.textContent = t(key, params);
}

function setAria(selector, key, params = {}) {
    const element = document.querySelector(selector);
    if (element) element.setAttribute('aria-label', t(key, params));
}

function applyStaticLocalization() {
    setAria('#color-button', 'aria.change_color');
    setAria('#status-text', 'status.connecting');
    setAria('#hand-count', 'aria.hand_cards');
    setAria('#interaction-button', 'aria.player_actions');
    setAria('#mobile-buttons-button', 'menu.buttons');
    setText('#cards .empty-msg', 'hand.waiting');
    setText('#menu-title', 'action.choose');
    setText('#action-all-toggle', 'action.all');
    setText('#action-play-table', 'action.play_table');
    setText('#action-flip', 'action.flip');
    setText('#action-play-zone', 'action.play_zone');
    setAria('#action-zone-layout', 'action.zone_layout_stack_aria');
    setText('#action-give', 'action.give');
    setText('#action-cancel', 'common.close');
    setText('#button-menu h2', 'menu.buttons');
    setText('#mobile-button-normal', 'mobile_buttons.normal');
    setText('#mobile-button-alt', 'mobile_buttons.alt_click');
    setText('#button-menu-close', 'common.close');
    setAria('#favorite-left', 'favorite.left_aria');
    setAria('#favorite-right', 'favorite.right_aria');
    setText('#favorite-title', 'favorite.title');
    setText('#favorite-remove', 'favorite.remove');
    setText('#favorite-close', 'common.close');
    setText('#interaction-menu h2', 'interaction.title');
    const typeSelect = document.getElementById('interaction-type');
    if (typeSelect?.options?.length >= 2) {
        typeSelect.options[0].textContent = t('interaction.draw_hidden');
        typeSelect.options[1].textContent = t('interaction.pick_open');
    }
    setText('#interaction-send', 'interaction.send_request');
    setText('#interaction-menu .hint', 'interaction.confirm_hint');
    const interactionHeadings = document.querySelectorAll('#interaction-menu h2');
    if (interactionHeadings[1]) interactionHeadings[1].textContent = t('interaction.incoming');
    if (interactionHeadings[2]) interactionHeadings[2].textContent = t('interaction.outgoing');
    setText('#interaction-close', 'common.close');
    setText('#open-pick-menu h2', 'open_pick.open_title');
    setText('#open-pick-confirm', 'open_pick.take');
    setText('#open-pick-cancel', 'common.cancel');
}

updateAppViewportHeight();
applyStaticLocalization();
buildColorDropdown();
buildSettingsMenu();
applyViewMode(localStorage.getItem(VIEW_MODE_STORAGE_KEY) || 'overlap');
applyDragModeSetting(localStorage.getItem(DRAG_MODE_STORAGE_KEY) || 'auto');
applyPlayerFilterSetting(localStorage.getItem(PLAYER_FILTER_STORAGE_KEY) || 'seated');
requestAnimationFrame(updateHeaderScroll);

socket.on('connect', () => {
    pythonSocketConnected = true;
    updateConnectionState();
    joinControlledColor(myColor);
});

socket.on('disconnect', () => {
    pythonSocketConnected = false;
    updateConnectionState();
});

socket.on('hand_updated', (data) => {
    if (data.color) {
        myColor = data.color;
        if (isAdmin) localStorage.setItem(ADMIN_COLOR_STORAGE_KEY, myColor);
        updateControlledColorChrome();
    }
    currentCards = Array.isArray(data.cards) ? data.cards : [];
    playerColors = Array.isArray(data.players) ? data.players : playerColors;
    if (Array.isArray(data.hand_zone_colors)) {
        handZoneColors = data.hand_zone_colors;
        handZoneColorsReceived = true;
    }
    if (Array.isArray(data.seated_colors)) {
        seatedColors = data.seated_colors;
        seatedColorsReceived = true;
    }
    occupiedColors = Array.isArray(data.occupied_colors) ? data.occupied_colors : occupiedColors;
    if (data.lua_connection && typeof data.lua_connection === 'object') {
        luaConnected = data.lua_connection.connected === true;
        luaLastContactAt = data.lua_connection.last_contact_at || null;
    }
    dropZones = Array.isArray(data.drop_zones) ? data.drop_zones : dropZones;
    mobileButtons = Array.isArray(data.mobile_buttons) ? data.mobile_buttons : mobileButtons;
    selectedGuids = new Set([...selectedGuids].filter(guid => currentCards.some(card => card.guid === guid)));
    renderCards();
    renderPlayerTargets();
    renderZoneTargets();
    renderMobileButtons();
    renderFavoriteButtons();
    updateHeaderCounts();
    buildColorDropdown();
    updateConnectionState();
});

socket.on('join_error', (data) => {
    setConnectionState('disconnected');
    showFatalMessage(localizedMessage(data, 'error', 'errors.color_unavailable'));
});

socket.on('card_action_result', (data) => {
    if (!data.ok) alert(localizedMessage(data, 'error', 'errors.action_failed'));
});

socket.on('mobile_button_action_result', (data) => {
    if (!data.ok) alert(localizedMessage(data, 'error', 'errors.mobile_button_action_failed'));
});

socket.on('admin_sync_result', (data) => {
    alert(localizedMessage(data, data?.ok ? 'message' : 'error', data?.ok ? 'settings.sync_all_hands_sent' : 'errors.action_failed'));
});

socket.on('interaction_updated', (data) => {
    incomingInteractions = Array.isArray(data.incoming_requests) ? data.incoming_requests : [];
    outgoingInteractions = Array.isArray(data.outgoing_requests) ? data.outgoing_requests : [];
    renderInteractions();
    updateInteractionButtonState();
});

socket.on('interaction_open_pick', (data) => {
    activeOpenPick = {
        request: data.request,
        cards: Array.isArray(data.cards) ? data.cards : [],
    };
    openPickSelectedGuids = new Set();
    renderOpenPick();
    openOpenPickMenu();
});

socket.on('interaction_result', (data) => {
    const requestData = data.request || null;
    if (!data.ok && activeOpenPick?.request?.id && requestData?.id === activeOpenPick.request.id) {
        activeOpenPick = null;
        openPickSelectedGuids = new Set();
        closeOpenPickMenu();
    }
    const shouldAlert =
        !data.ok &&
        (data.message || data.message_key) &&
        (!requestData || requestData.from_color === myColor);
    if (shouldAlert) {
        alert(localizedMessage(data, 'message'));
    }
});

function renderCards() {
    container.replaceChildren();
    updateSelectionInfo();

    if (currentCards.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-msg';
        empty.textContent = t('hand.empty');
        container.appendChild(empty);
        requestAnimationFrame(updateHandScrollbar);
        return;
    }

    getDisplayCards().forEach(card => container.appendChild(createCardElement(card)));

    updateCardSelectionClasses();
    requestAnimationFrame(updateHandScrollbar);
}

function getDisplayCards() {
    return getDisplayCardsForList(currentCards);
}

function getDisplayCardsForList(cards) {
    if (!isPortrait()) {
        return cards;
    }
    const topRow = [];
    const bottomRow = [];
    for (let i = 0; i < cards.length; i++) {
        if (i % 2 === 0) {
            topRow.push(cards[i]);
        } else {
            bottomRow.push(cards[i]);
        }
    }
    const displayCards = [];
    const maxColumns = Math.max(topRow.length, bottomRow.length);
    for (let i = 0; i < maxColumns; i++) {
        if (topRow[i]) displayCards.push(topRow[i]);
        if (bottomRow[i]) displayCards.push(bottomRow[i]);
    }
    return displayCards;
}

function isPortrait() {
    return window.matchMedia('(orientation: portrait)').matches;
}

function getEstimatedPortraitSingleRowCapacity() {
    if (currentCards.length === 0) {
        return 1;
    }

    const availableWidth = Math.max(1, container.clientWidth - 40);
    const firstCard = currentCards[0];
    const cardWidth = estimateCardWidth(firstCard);

    if (document.body.classList.contains('view-overlap')) {
        const overlap = Math.abs(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-overlap')) || 58);
        const visibleStep = Math.max(32, cardWidth - overlap);
        return Math.max(1, Math.floor((availableWidth - cardWidth) / visibleStep) + 1);
    }

    const gap = 15;
    return Math.max(1, Math.floor((availableWidth + gap) / (cardWidth + gap)));
}

function estimateCardWidth(card) {
    return getResponsiveCardSize(card).width;
}

function createCardElement(card) {
    const cardDiv = document.createElement('div');
    cardDiv.className = 'card';
    cardDiv.dataset.guid = card.guid;
    applyTTSCardSize(cardDiv, card);

    const imageElement = createCardImage(card);
    const title = document.createElement('div');
    title.className = 'card-title';
    let displayName = card.name ? (card.face_down ? '?' : card.name) : '';
    title.textContent = displayName;
    if (!displayName) title.style.display = 'none';

    const descriptionText = typeof card.desc === 'string' ? card.desc.trim() : '';
    if (descriptionText) {
        const helpButton = document.createElement('button');
        helpButton.type = 'button';
        helpButton.className = 'card-help';
        helpButton.textContent = '?';
        helpButton.addEventListener('pointerdown', stopCardHelpEvent);
        helpButton.addEventListener('click', (event) => {
            event.stopPropagation();
            toggleCardDescription(card.guid);
        });

        const descriptionTooltip = document.createElement('div');
        descriptionTooltip.className = 'card-description-tooltip';
        descriptionTooltip.dataset.guid = card.guid;
        descriptionTooltip.textContent = descriptionText;
        descriptionTooltip.addEventListener('pointerdown', stopCardHelpEvent);
        descriptionTooltip.addEventListener('click', stopCardHelpEvent);

        imageElement.appendChild(helpButton);
        imageElement.appendChild(descriptionTooltip);
    }

    imageElement.appendChild(title);
    cardDiv.appendChild(imageElement);

    cardDiv.addEventListener('pointerdown', (event) => onPointerDown(event, card.guid));
    cardDiv.addEventListener('pointermove', onPointerMove);
    cardDiv.addEventListener('pointerup', onPointerUp);
    cardDiv.addEventListener('pointercancel', onPointerCancel);
    return cardDiv;
}

function stopCardHelpEvent(event) {
    event.stopPropagation();
}

function stopCardZoomEvent(event) {
    event.stopPropagation();
    event.preventDefault();
}

function toggleCardDescription(guid) {
    const tooltip = document.querySelector(`.card-description-tooltip[data-guid="${guid}"]`);
    if (!tooltip) return;

    const shouldShow = tooltip.style.display !== 'block';
    hideCardDescriptions();
    if (shouldShow) {
        tooltip.style.display = 'block';
    }
}

function hideCardDescriptions() {
    for (const tooltip of document.querySelectorAll('.card-description-tooltip')) {
        tooltip.style.display = 'none';
    }
}

function openCardZoom(guid) {
    const card = currentCards.find(item => item.guid === guid);
    if (!card || !cardZoomMenu || !cardZoomCard) return;

    closeAllMenus();
    hideCardDescriptions();
    cardZoomGuid = guid;
    renderCardZoom();
    cardZoomMenu.style.display = 'flex';
}

function renderCardZoom() {
    const card = currentCards.find(item => item.guid === cardZoomGuid);
    if (!card || !cardZoomCard) return;

    cardZoomCard.replaceChildren();
    cardZoomCard.classList.remove('dragging');
    cardZoomCard.style.transform = '';

    const imageElement = createCardImage(card);
    const zoomSize = getZoomCardSize(card);
    imageElement.style.width = `${zoomSize.width}px`;
    imageElement.style.height = `${zoomSize.height}px`;

    const name = typeof card.name === 'string' ? card.name.trim() : '';
    const desc = typeof card.desc === 'string' ? card.desc.trim() : '';
    const infoText = [name, desc].filter(Boolean).join('\n\n');

    cardZoomCard.appendChild(imageElement);
    if (!infoText) {
        return;
    }

    const helpButton = document.createElement('button');
    helpButton.type = 'button';
    helpButton.className = 'card-zoom-help';
    helpButton.textContent = '?';

    const info = document.createElement('div');
    info.className = 'card-zoom-info';
    info.textContent = infoText;

    helpButton.addEventListener('pointerdown', stopCardZoomEvent);
    helpButton.addEventListener('click', (event) => {
        event.stopPropagation();
        event.preventDefault();
        info.classList.toggle('visible');
    });
    info.addEventListener('pointerdown', stopCardZoomEvent);
    info.addEventListener('click', stopCardZoomEvent);

    cardZoomCard.appendChild(helpButton);
    cardZoomCard.appendChild(info);
}

function getZoomCardSize(card) {
    const scaleX = Number(card.scale_x || 1);
    const scaleZ = Number(card.scale_z || 1);
    let baseWidth = TTS_CARD_BASE_WIDTH * scaleX;
    let baseHeight = TTS_CARD_BASE_HEIGHT * scaleZ;

    if (card.sideways) {
        const tmp = baseWidth;
        baseWidth = baseHeight;
        baseHeight = tmp;
    }

    const maxWidth = Math.max(1, window.innerWidth - 36);
    const maxHeight = Math.max(1, getVisibleViewportHeight() - 36);
    const factor = Math.min(maxWidth / baseWidth, maxHeight / baseHeight);

    return {
        width: Math.max(1, baseWidth * factor),
        height: Math.max(1, baseHeight * factor),
    };
}

function closeCardZoom() {
    if (!cardZoomMenu || !cardZoomCard) return;
    cardZoomMenu.style.display = 'none';
    cardZoomCard.replaceChildren();
    cardZoomGuid = null;
    cardZoomDragStart = null;
    cardZoomDragging = false;
    cardZoomDragMoved = false;
    cardZoomCard.classList.remove('dragging');
    cardZoomCard.style.transform = '';
}

function currentCardZoomIndex() {
    return currentCards.findIndex(card => card.guid === cardZoomGuid);
}

function showZoomCardAtIndex(index) {
    if (index < 0 || index >= currentCards.length) return false;
    cardZoomGuid = currentCards[index].guid;
    renderCardZoom();
    return true;
}

function startCardZoomDrag(event) {
    if (!cardZoomMenu || cardZoomMenu.style.display !== 'flex') return;
    if (event.button !== undefined && event.button !== 0) return;

    cardZoomDragging = true;
    cardZoomDragMoved = false;
    cardZoomDragStart = { x: event.clientX, y: event.clientY };
    cardZoomCard?.classList.add('dragging');
    cardZoomMenu.setPointerCapture(event.pointerId);
}

function moveCardZoomDrag(event) {
    if (!cardZoomDragging || !cardZoomDragStart || !cardZoomCard) return;

    const dx = event.clientX - cardZoomDragStart.x;
    const dy = event.clientY - cardZoomDragStart.y;
    if (Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) {
        cardZoomDragMoved = true;
    }

    if (cardZoomDragMoved) {
        event.preventDefault();
        cardZoomCard.style.transform = `translateX(${dx}px)`;
    }
}

function finishCardZoomDrag(event) {
    if (!cardZoomDragging || !cardZoomDragStart) return;

    const dx = event.clientX - cardZoomDragStart.x;
    const index = currentCardZoomIndex();
    const threshold = Math.max(48, window.innerWidth * 0.16);
    let changed = false;

    if (Math.abs(dx) >= threshold && index >= 0) {
        changed = dx < 0
            ? showZoomCardAtIndex(index + 1)
            : showZoomCardAtIndex(index - 1);
    }

    if (!changed && cardZoomCard) {
        cardZoomCard.classList.remove('dragging');
        cardZoomCard.style.transform = '';
    }

    cardZoomDragging = false;
    cardZoomDragStart = null;

    if (!cardZoomDragMoved) {
        closeCardZoom();
    }
    cardZoomDragMoved = false;
}

function cancelCardZoomDrag() {
    cardZoomDragging = false;
    cardZoomDragStart = null;
    cardZoomDragMoved = false;
    if (cardZoomCard) {
        cardZoomCard.classList.remove('dragging');
        cardZoomCard.style.transform = '';
    }
}

function onPointerDown(event, guid) {
    if (event.button !== undefined && event.button !== 0) return;
    closeAllMenus();
    closeCardZoom();
    hideCardDescriptions();
    draggingGuid = guid;
    dragStarted = false;
    pressStart = { x: event.clientX, y: event.clientY, guid };
    event.currentTarget.setPointerCapture(event.pointerId);

    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
        pressTimer = null;
        openCardZoom(guid);
        pressStart = null;
        draggingGuid = null;
        dragStarted = false;
    }, LONG_PRESS_MS);
}

function onPointerMove(event) {
    if (!pressStart || !draggingGuid) return;
    const dx = event.clientX - pressStart.x;
    const dy = event.clientY - pressStart.y;
    const distance = Math.hypot(dx, dy);

    if (distance > DRAG_THRESHOLD_PX) {
        clearTimeout(pressTimer);
        pressTimer = null;

        if (!dragStarted) startDragGroup(draggingGuid);
        dragStarted = true;
        moveDragGroup(event.clientX, event.clientY);
    }
}

function onPointerUp(event) {
    clearTimeout(pressTimer);
    pressTimer = null;

    if (dragStarted) {
        finishDragGroup();
    } else if (pressStart && !menuIsOpen()) {
        toggleSelection(pressStart.guid);
    }

    pressStart = null;
    draggingGuid = null;
    dragStarted = false;
}

function onPointerCancel() {
    clearTimeout(pressTimer);
    pressStart = null;
    draggingGuid = null;
    dragStarted = false;
    dragGuids = [];
    cleanupDropClasses();
}

function toggleSelection(guid) {
    if (selectedGuids.has(guid)) selectedGuids.delete(guid);
    else selectedGuids.add(guid);

    updateCardSelectionClasses();
    updateSelectionInfo();
}

function selectedOrSingleGuids() {
    if (selectedGuids.size > 0) {
        return currentCards.map(card => card.guid).filter(guid => selectedGuids.has(guid));
    }
    return draggingGuid ? [draggingGuid] : [];
}

function allHandGuids() {
    return currentCards.map(card => card.guid).filter(Boolean);
}

function actionTargetGuids() {
    return actionMenuAllCards ? allHandGuids() : selectedOrSingleGuids();
}

function startDragGroup(guid) {
    if (selectedGuids.has(guid)) {
        dragGuids = currentCards
            .map(card => card.guid)
            .filter(cardGuid => selectedGuids.has(cardGuid));
    } else {
        selectedGuids.add(guid);
        dragGuids = [guid];
    }

    updateCardSelectionClasses();

    for (const el of document.querySelectorAll('.card')) {
        if (dragGuids.includes(el.dataset.guid)) {
            el.classList.add('dragging');
        }
    }
}

function moveDragGroup(x, y) {
    cleanupDropClasses();

    if (getActiveDragMode() === 'swap') {
        const target = document.elementFromPoint(x, y)?.closest?.('.card');
        if (!target || dragGuids.includes(target.dataset.guid)) return;
        target.classList.add('swap-target');
        return;
    }

    const slot = nearestMoveDropSlot(x, y);
    if (!slot) return;
    showDropSlotMarker(slot);
}

function nearestMoveDropSlot(x, y) {
    const displayCards = getDisplayCards();
    const anchors = [];

    for (const card of displayCards) {
        if (!card.guid || dragGuids.includes(card.guid)) continue;
        const el = document.querySelector(`.card[data-guid="${card.guid}"]`);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        anchors.push({
            guid: card.guid,
            rect,
            centerX: rect.left + rect.width / 2,
            centerY: rect.top + rect.height / 2,
        });
    }

    if (!anchors.length) return null;

    let insertIndex = 0;
    for (const anchor of anchors) {
        const horizontal = Math.abs(x - anchor.centerX) >= Math.abs(y - anchor.centerY);
        const after = horizontal ? x > anchor.centerX : y > anchor.centerY;
        if (after) {
            insertIndex = currentCards.findIndex(card => card.guid === anchor.guid) + 1;
        } else {
            break;
        }
    }

    const leftAnchor = anchors
        .filter(anchor => currentCards.findIndex(card => card.guid === anchor.guid) < insertIndex)
        .at(-1) || null;
    const rightAnchor = anchors.find(
        anchor => currentCards.findIndex(card => card.guid === anchor.guid) >= insertIndex
    ) || null;

    return { insertIndex, leftAnchor, rightAnchor };
}

function showDropSlotMarker(slot) {
    let marker = document.getElementById('drop-slot-marker');
    if (!marker) {
        marker = document.createElement('div');
        marker.id = 'drop-slot-marker';
        marker.className = 'drop-slot-marker';
        document.body.appendChild(marker);
    }

    const leftRect = slot.leftAnchor?.rect || null;
    const rightRect = slot.rightAnchor?.rect || null;
    let x = 0;
    let top = 0;
    let bottom = 0;

    if (leftRect && rightRect) {
        x = (leftRect.right + rightRect.left) / 2;
        top = Math.min(leftRect.top, rightRect.top);
        bottom = Math.max(leftRect.bottom, rightRect.bottom);
    } else if (rightRect) {
        x = rightRect.left - 10;
        top = rightRect.top;
        bottom = rightRect.bottom;
    } else if (leftRect) {
        x = leftRect.right + 10;
        top = leftRect.top;
        bottom = leftRect.bottom;
    } else {
        return;
    }

    marker.dataset.insertIndex = String(slot.insertIndex);
    marker.style.left = `${x}px`;
    marker.style.top = `${top}px`;
    marker.style.height = `${Math.max(36, bottom - top)}px`;
}

function finishDragGroup() {
    const dragMode = getActiveDragMode();
    const marker = dragMode === 'swap'
        ? document.querySelector('.card.swap-target')
        : document.getElementById('drop-slot-marker');

    if (!marker) {
        cleanupDropClasses();
        dragGuids = [];
        return;
    }

    const targetGuid = marker.dataset.guid;

    if (dragMode === 'swap') {
        swapSingleDraggedCardWithTarget(targetGuid);
        cleanupDropClasses();
        selectedGuids.clear();
        renderCards();
        sendCardAction('reorder_hand', currentCards.map(card => card.guid));
        dragGuids = [];
        updateHandScrollbar();
        return;
    }

    const movingCards = currentCards.filter(card => dragGuids.includes(card.guid));
    const remainingCards = currentCards.filter(card => !dragGuids.includes(card.guid));

    const originalInsertIndex = Number(marker.dataset.insertIndex || currentCards.length);
    const movedBeforeSlot = currentCards
        .slice(0, originalInsertIndex)
        .filter(card => dragGuids.includes(card.guid))
        .length;
    const insertIndex = Math.max(
        0,
        Math.min(remainingCards.length, originalInsertIndex - movedBeforeSlot)
    );

    currentCards = [
        ...remainingCards.slice(0, insertIndex),
        ...movingCards,
        ...remainingCards.slice(insertIndex)
    ];

    cleanupDropClasses();
    selectedGuids.clear();
    renderCards();
    sendCardAction('reorder_hand', currentCards.map(card => card.guid));
    dragGuids = [];
    updateHandScrollbar();
}

function swapSingleDraggedCardWithTarget(targetGuid) {
    if (!draggingGuid || !targetGuid || draggingGuid === targetGuid) {
        return;
    }

    const draggedIndex = currentCards.findIndex(card => card.guid === draggingGuid);
    const targetIndex = currentCards.findIndex(card => card.guid === targetGuid);

    if (draggedIndex < 0 || targetIndex < 0) {
        return;
    }

    const nextCards = [...currentCards];
    const tmp = nextCards[draggedIndex];

    nextCards[draggedIndex] = nextCards[targetIndex];
    nextCards[targetIndex] = tmp;

    currentCards = nextCards;
}

function cleanupDropClasses() {
    for (const el of document.querySelectorAll('.dragging,.drop-before,.drop-after,.swap-target')) {
        el.classList.remove('dragging', 'drop-before', 'drop-after', 'swap-target');
    }
    document.getElementById('drop-slot-marker')?.remove();
}

function updateCardSelectionClasses() {
    const displayCards = getDisplayCards();

    for (let i = 0; i < displayCards.length; i++) {
        const card = displayCards[i];
        const el = document.querySelector(`.card[data-guid="${card.guid}"]`);
        if (!el) continue;

        const isSelected = selectedGuids.has(card.guid);
        const prevSelected = i > 0 && selectedGuids.has(displayCards[i - 1].guid);
        const nextSelected = i < displayCards.length - 1 && selectedGuids.has(displayCards[i + 1].guid);

        el.classList.toggle('selected', isSelected);
        el.classList.toggle('selected-run-start', isSelected && !prevSelected);
        el.classList.toggle('selected-after-selected', isSelected && prevSelected);
        el.classList.toggle('selected-run-end', isSelected && !nextSelected);
    }

    updateSelectionInfo();
    requestAnimationFrame(updateHandScrollbar);
}

function updateSelectionInfo() {
    selectionInfo.textContent = selectedGuids.size ? `+${selectedGuids.size}` : '';
    selectionInfo.classList.toggle('active', selectedGuids.size > 0);
    updateHeaderCounts();
    renderFavoriteButtons();
}

function updateHeaderCounts() {
    if (handCountNumber) {
        handCountNumber.textContent = String(currentCards.length);
    }
}

function updateControlledColorChrome() {
    document.getElementById('header-bar').style.borderBottomColor = colorMap[myColor] || '#555';
    document.getElementById('header-bar').style.borderRightColor = colorMap[myColor] || '#555';
    document.getElementById('player-color-square').style.background = colorMap[myColor] || '#777';
}

function setConnectionState(state) {
    if (!statusIndicator) return;
    statusIndicator.dataset.state = state;
    const labels = {
        connected: t('status.connected'),
        'lua-disconnected': t('status.lua_disconnected'),
        connecting: t('status.connecting'),
        disconnected: t('status.disconnected'),
    };
    statusIndicator.setAttribute('aria-label', labels[state] || labels.connecting);
}

function updateConnectionState() {
    if (!pythonSocketConnected) {
        setConnectionState('disconnected');
        return;
    }
    setConnectionState(luaConnected ? 'connected' : 'lua-disconnected');
}

function connectionInfoText() {
    if (!pythonSocketConnected) {
        return t('status.info_disconnected');
    }
    if (!luaConnected) {
        return t('status.info_lua_disconnected');
    }
    return t('status.info_connected');
}

function showConnectionInfo() {
    alert(connectionInfoText());
}

function requestAdminSyncAllHands() {
    if (!isAdmin) return;
    socket.emit('admin_sync_all_hands', {
        color: myColor,
        language: navigator.language || '',
        languages: navigator.languages || [],
    });
}

function joinControlledColor(color) {
    if (!color) return;
    socket.emit('join', {
        color,
        client_id: clientId,
        is_admin: isAdmin,
        language: navigator.language || '',
        languages: navigator.languages || [],
    });
}

function showFatalMessage(message) {
    closeAllMenus();
    container.replaceChildren();
    const error = document.createElement('div');
    error.className = 'empty-msg';
    error.textContent = message;
    container.appendChild(error);
}

function uniqueColors(colors) {
    return (Array.isArray(colors) ? colors : [])
        .filter((color, index, list) => color && list.indexOf(color) === index);
}

function normalizePlayerFilter(mode) {
    return ['all', 'hand', 'seated'].includes(mode) ? mode : 'seated';
}

function getActivePlayerFilter() {
    return normalizePlayerFilter(
        document.querySelector('input[name="player-filter"]:checked')?.value ||
        localStorage.getItem(PLAYER_FILTER_STORAGE_KEY) ||
        'seated'
    );
}

function selectablePlayerColors() {
    const allColors = uniqueColors(playerColors.length ? playerColors : defaultPlayerColors);
    const mode = getActivePlayerFilter();
    if (mode === 'all') return allColors;
    if (mode === 'hand') {
        if (!handZoneColorsReceived) return allColors;
        return uniqueColors(handZoneColors).filter(color => allColors.includes(color));
    }
    if (!seatedColorsReceived) return allColors;
    const seated = uniqueColors(seatedColors).filter(color => allColors.includes(color));
    return seated;
}

function buildColorDropdown() {
    if (!colorDropdown) return;
    const colors = selectablePlayerColors();
    colorDropdown.replaceChildren();
    colors.forEach(color => {
        const occupied = occupiedColors.includes(color);
        const disabled = !isAdmin && occupied && color !== myColor;
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'color-option';
        option.classList.toggle('active', color === myColor);
        option.classList.toggle('occupied', occupied);
        option.disabled = disabled;
        option.title = disabled ? t('errors.color_occupied') : '';

        const swatch = document.createElement('span');
        swatch.className = 'player-color-square';
        swatch.style.background = colorMap[color] || '#777';
        option.appendChild(swatch);

        const label = document.createElement('span');
        label.textContent = disabled ? t('color.occupied_label', {color}) : color;
        option.appendChild(label);

        option.addEventListener('click', () => {
            if (!disabled) switchPlayerColor(color);
        });
        colorDropdown.appendChild(option);
    });
}

function toggleColorDropdown() {
    if (!colorDropdown || !colorButton) return;
    const wasOpen = colorDropdown.classList.contains('open');
    closeAllMenus();
    if (!wasOpen) {
        positionColorDropdown();
        colorDropdown.classList.add('open');
    }
}

function positionColorDropdown() {
    if (!colorDropdown || !colorButton) return;
    const rect = colorButton.getBoundingClientRect();
    const margin = 6;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;

    if (isPortrait()) {
        colorDropdown.style.left = `${Math.max(8, Math.min(rect.left, viewportWidth - 220))}px`;
        colorDropdown.style.top = `${rect.bottom + margin}px`;
    } else {
        colorDropdown.style.left = `${rect.right + margin}px`;
        colorDropdown.style.top = `${Math.max(8, rect.top)}px`;
    }
}

function closeColorDropdown() {
    colorDropdown?.classList.remove('open');
}

function switchPlayerColor(color) {
    if (!color || color === myColor) {
        closeColorDropdown();
        return;
    }
    if (isAdmin) {
        myColor = color;
        localStorage.setItem(ADMIN_COLOR_STORAGE_KEY, myColor);
        updateControlledColorChrome();
        joinControlledColor(myColor);
        closeColorDropdown();
        return;
    }
    if (occupiedColors.includes(color)) {
        alert(t('errors.color_occupied'));
        closeColorDropdown();
        return;
    }
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set('color', color);
    window.location.href = nextUrl.toString();
}

function formatLongPressSeconds() {
    const seconds = LONG_PRESS_MS / 1000;
    if (Number.isInteger(seconds)) {
        return String(seconds);
    }
    const formatted = seconds.toFixed(1);
    return formatted.endsWith('.0') ? formatted.slice(0, -2) : formatted;
}

function buildSettingsMenu() {
    const longPressSeconds = formatLongPressSeconds();

    function createRadioOption(name, value, labelKey) {
        const label = document.createElement('label');
        label.className = 'settings-option';

        const input = document.createElement('input');
        input.type = 'radio';
        input.name = name;
        input.value = value;

        const span = document.createElement('span');
        span.textContent = t(labelKey);

        label.append(input, span);
        return label;
    }

    function createSettingsRow(titleKey, optionsClass, inputName, options, helpKey) {
        const row = document.createElement('div');
        row.className = 'settings-row';

        const title = document.createElement('div');
        title.className = 'settings-row-title';
        title.textContent = t(titleKey);

        const optionGroup = document.createElement('div');
        optionGroup.className = `settings-options ${optionsClass}`;
        options.forEach(option => {
            optionGroup.appendChild(createRadioOption(inputName, option.value, option.labelKey));
        });

        const helpButton = document.createElement('button');
        helpButton.className = 'settings-help';
        helpButton.type = 'button';
        helpButton.dataset.help = helpKey;
        helpButton.textContent = '?';

        row.append(title, optionGroup, helpButton);
        return row;
    }

    const title = document.createElement('h2');
    title.textContent = t('settings.title');

    const tooltip = document.createElement('div');
    tooltip.className = 'settings-tooltip';
    tooltip.id = 'settings-tooltip';

    const hint = document.createElement('div');
    hint.className = 'hint';
    hint.textContent = t('settings.hint', {seconds: longPressSeconds});

    const closeButton = document.createElement('button');
    closeButton.id = 'settings-close';
    closeButton.className = 'secondary';
    closeButton.type = 'button';
    closeButton.textContent = t('common.close');

    const children = [
        title,
        createSettingsRow('settings.view', 'two', 'view-mode', [
            {value: 'overlap', labelKey: 'settings.overlap'},
            {value: 'grid', labelKey: 'settings.grid_short'},
        ], 'view'),
        createSettingsRow('settings.drag', 'three', 'drag-mode', [
            {value: 'auto', labelKey: 'settings.auto'},
            {value: 'swap', labelKey: 'settings.swap'},
            {value: 'move', labelKey: 'settings.move_short'},
        ], 'drag'),
        createSettingsRow('settings.players', 'three', 'player-filter', [
            {value: 'all', labelKey: 'settings.players_all'},
            {value: 'hand', labelKey: 'settings.players_hand'},
            {value: 'seated', labelKey: 'settings.players_seated'},
        ], 'players'),
        tooltip,
    ];

    if (isAdmin) {
        const syncButton = document.createElement('button');
        syncButton.id = 'admin-sync-all-hands';
        syncButton.className = 'primary';
        syncButton.type = 'button';
        syncButton.textContent = t('settings.sync_all_hands');
        children.push(syncButton);
    }

    children.push(hint, closeButton);
    settingsMenu.replaceChildren(...children);
}

function openMenu(options = {}) {
    const nextMode = options.mode === 'favorite' ? 'favorite' : 'execute';
    actionMenuAllCards = !!options.allCards;
    const count = actionMenuAllCards ? allHandGuids().length : selectedOrSingleGuids().length;
    if (!count && nextMode !== 'favorite') return;

    closeCardZoom();
    closeSettings();
    closeButtonMenu();
    closeFavoriteMenu({keepSlot: nextMode === 'favorite'});
    closeInteractionMenu();
    closeColorDropdown();
    activeMenuMode = nextMode;
    renderPlayerTargets();
    renderZoneTargets();
    applyActionMenuFavoriteDefaults();
    updateActionMenuHeader();
    updateDropZoneLayoutButton();
    updateActionMenuMode();
    backdrop.style.display = 'block';
    menu.style.display = 'block';
    hideActionHelp();
}

function openMenuFromHandCount() {
    if (currentCards.length === 0) return;
    openMenu({ allCards: selectedGuids.size === 0 });
}

function closeMenu() {
    const wasFavoriteMode = activeMenuMode === 'favorite';
    menu.style.display = 'none';
    actionMenuAllCards = false;
    activeMenuMode = 'execute';
    if (wasFavoriteMode) activeFavoriteSlot = null;
    updateActionMenuHeader();
    updateActionMenuMode();
    hideActionHelp();
    if (!settingsIsOpen() && !buttonMenuIsOpen() && !favoriteMenuIsOpen() && !interactionMenuIsOpen() && !openPickMenuIsOpen()) backdrop.style.display = 'none';
}

function updateActionMenuHeader() {
    if (activeMenuMode === 'favorite') {
        document.getElementById('menu-title').textContent = t('favorite.title_slot', {slot: favoriteSlotLabel(activeFavoriteSlot)});
    } else {
        document.getElementById('menu-title').textContent = actionMenuAllCards
        ? t('action.title_all')
        : t('action.title_count', {count: selectedOrSingleGuids().length});
    }

    if (!actionAllToggle) return;
    actionAllToggle.style.display = activeMenuMode === 'favorite' ? 'none' : '';
    actionAllToggle.classList.toggle('active', actionMenuAllCards);
    actionAllToggle.setAttribute('aria-pressed', actionMenuAllCards ? 'true' : 'false');
}

function updateActionMenuMode() {
    const playTable = document.getElementById('action-play-table');
    const flip = document.getElementById('action-flip');
    const playZone = document.getElementById('action-play-zone');
    const give = document.getElementById('action-give');
    const cancel = document.getElementById('action-cancel');
    if (!playTable || !flip || !playZone || !give || !cancel) return;

    playTable.textContent = t('action.play_table');
    flip.textContent = t('action.flip');
    playZone.textContent = t('action.play_zone');
    give.textContent = t('action.give');
    cancel.textContent = t('common.close');
    [playTable, flip, playZone, give].forEach(button => {
        button.classList.toggle('favorite-save-choice', activeMenuMode === 'favorite');
    });
}

function applyActionMenuFavoriteDefaults() {
    if (activeMenuMode !== 'favorite') return;
    const favorite = currentFavorite(activeFavoriteSlot);
    if (favorite?.type === 'drop_zone') {
        dropZoneSpreadCards = !!favorite.spread_cards;
        const zoneSelect = document.getElementById('zone-target');
        const zoneValue = favorite.target ? JSON.stringify(favorite.target) : '';
        if (zoneSelect && zoneValue && Array.from(zoneSelect.options).some(option => option.value === zoneValue)) {
            zoneSelect.value = zoneValue;
        }
    }
    if (favorite?.type === 'card_action' && favorite.action === 'give_to_player' && favorite.target_color) {
        giveTargetColor = favorite.target_color;
        renderPlayerTargets();
    }
}

function toggleActionMenuAllCards() {
    actionMenuAllCards = !actionMenuAllCards;
    updateActionMenuHeader();
    hideActionHelp();
}

function toggleDropZoneSpreadCards() {
    dropZoneSpreadCards = !dropZoneSpreadCards;
    updateDropZoneLayoutButton();
    hideActionHelp();
}

function updateDropZoneLayoutButton() {
    if (!actionZoneLayoutButton) return;
    actionZoneLayoutButton.classList.toggle('active', dropZoneSpreadCards);
    actionZoneLayoutButton.textContent = dropZoneSpreadCards ? '↔' : '▣';
    actionZoneLayoutButton.title = dropZoneSpreadCards ? t('action.zone_layout_spread') : t('action.zone_layout_stack');
    actionZoneLayoutButton.setAttribute('aria-label', dropZoneSpreadCards ? t('action.zone_layout_spread_aria') : t('action.zone_layout_stack_aria'));
    actionZoneLayoutButton.setAttribute('aria-pressed', dropZoneSpreadCards ? 'true' : 'false');
}

function openSettings() {
    closeMenu();
    closeButtonMenu();
    closeFavoriteMenu();
    closeInteractionMenu();
    closeColorDropdown();
    backdrop.style.display = 'block';
    settingsMenu.style.display = 'block';
    hideSettingsHelp();
}

function closeSettings() {
    settingsMenu.style.display = 'none';
    hideSettingsHelp();
    if (!menuIsOpen() && !buttonMenuIsOpen() && !favoriteMenuIsOpen() && !interactionMenuIsOpen() && !openPickMenuIsOpen()) backdrop.style.display = 'none';
}

function openButtonMenu(options = {}) {
    const nextMode = options.mode === 'favorite' ? 'favorite' : 'execute';
    closeMenu();
    closeSettings();
    closeFavoriteMenu({keepSlot: nextMode === 'favorite'});
    closeInteractionMenu();
    closeColorDropdown();
    activeMenuMode = nextMode;
    if (activeMenuMode === 'favorite') {
        const favorite = currentFavorite(activeFavoriteSlot);
        mobileButtonAltClick = favorite?.type === 'mobile_button' ? !!favorite.alt_click : false;
    }
    updateMobileButtonModeButtons();
    renderMobileButtons();
    backdrop.style.display = 'block';
    buttonMenu.style.display = 'block';
    hideButtonHelp();
}

function closeButtonMenu() {
    const wasFavoriteMode = activeMenuMode === 'favorite';
    buttonMenu.style.display = 'none';
    activeMenuMode = 'execute';
    if (wasFavoriteMode) activeFavoriteSlot = null;
    hideButtonHelp();
    if (!menuIsOpen() && !settingsIsOpen() && !favoriteMenuIsOpen() && !interactionMenuIsOpen() && !openPickMenuIsOpen()) backdrop.style.display = 'none';
}

function openFavoriteMenu(slot) {
    closeMenu();
    closeSettings();
    closeButtonMenu();
    closeInteractionMenu();
    closeColorDropdown();
    activeMenuMode = 'execute';
    activeFavoriteSlot = slot;
    renderFavoriteMenu();
    backdrop.style.display = 'block';
    favoriteMenu.style.display = 'block';
}

function closeFavoriteMenu(options = {}) {
    favoriteMenu.style.display = 'none';
    if (!options.keepSlot) {
        activeFavoriteSlot = null;
    }
    if (!menuIsOpen() && !settingsIsOpen() && !buttonMenuIsOpen() && !interactionMenuIsOpen() && !openPickMenuIsOpen()) backdrop.style.display = 'none';
}

function openInteractionMenu(options = {}) {
    const nextMode = options.mode === 'favorite' ? 'favorite' : 'execute';
    closeMenu();
    closeSettings();
    closeButtonMenu();
    closeFavoriteMenu({keepSlot: nextMode === 'favorite'});
    closeColorDropdown();
    activeMenuMode = nextMode;
    renderPlayerTargets();
    applyInteractionMenuFavoriteDefaults();
    renderInteractions();
    updateInteractionMenuMode();
    backdrop.style.display = 'block';
    interactionMenu.style.display = 'block';
}

function closeInteractionMenu() {
    const wasFavoriteMode = activeMenuMode === 'favorite';
    interactionMenu.style.display = 'none';
    activeMenuMode = 'execute';
    if (wasFavoriteMode) activeFavoriteSlot = null;
    updateInteractionMenuMode();
    if (!menuIsOpen() && !settingsIsOpen() && !buttonMenuIsOpen() && !favoriteMenuIsOpen() && !openPickMenuIsOpen()) backdrop.style.display = 'none';
}

function updateInteractionMenuMode() {
    const sendButton = document.getElementById('interaction-send');
    if (!sendButton) return;
    sendButton.textContent = t('interaction.send_request');
    sendButton.classList.toggle('favorite-save-choice', activeMenuMode === 'favorite');
}

function applyInteractionMenuFavoriteDefaults() {
    if (activeMenuMode !== 'favorite') return;
    const favorite = currentFavorite(activeFavoriteSlot);
    if (favorite?.type !== 'interaction_request') return;
    if (favorite.target_color) {
        interactionTargetColor = favorite.target_color;
        renderPlayerTargets();
    }
    const typeSelect = document.getElementById('interaction-type');
    const countInput = document.getElementById('interaction-count');
    if (typeSelect && favorite.interaction_type) {
        typeSelect.value = favorite.interaction_type;
    }
    if (countInput) {
        countInput.value = String(favorite.count || 1);
    }
}

function openOpenPickMenu() {
    closeMenu();
    closeSettings();
    closeButtonMenu();
    closeFavoriteMenu();
    closeInteractionMenu();
    closeColorDropdown();
    backdrop.style.display = 'block';
    openPickMenu.style.display = 'block';
}

function closeOpenPickMenu() {
    openPickMenu.style.display = 'none';
    if (!menuIsOpen() && !settingsIsOpen() && !buttonMenuIsOpen() && !favoriteMenuIsOpen() && !interactionMenuIsOpen()) backdrop.style.display = 'none';
}

function closeAllMenus() {
    menu.style.display = 'none';
    buttonMenu.style.display = 'none';
    favoriteMenu.style.display = 'none';
    interactionMenu.style.display = 'none';
    settingsMenu.style.display = 'none';
    if (!openPickMenuIsOpen()) backdrop.style.display = 'none';
    actionMenuAllCards = false;
    updateActionMenuHeader();
    hideActionHelp();
    hideButtonHelp();
    hideSettingsHelp();
    activeMenuMode = 'execute';
    activeFavoriteSlot = null;
    closeColorDropdown();
    closePlayerTargetPickers();
}

function menuIsOpen() {
    return menu.style.display === 'block';
}

function settingsIsOpen() {
    return settingsMenu.style.display === 'block';
}

function buttonMenuIsOpen() {
    return buttonMenu.style.display === 'block';
}

function favoriteMenuIsOpen() {
    return favoriteMenu.style.display === 'block';
}

function interactionMenuIsOpen() {
    return interactionMenu.style.display === 'block';
}

function openPickMenuIsOpen() {
    return openPickMenu.style.display === 'block';
}

function getVisibleViewportHeight() {
    return window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight || 1;
}

function updateAppViewportHeight() {
    document.documentElement.style.setProperty('--app-height', `${getVisibleViewportHeight()}px`);
}

function refreshViewportLayout(forceRender = false) {
    if (!forceRender && activeMenuContainsFocusedInput()) {
        requestAnimationFrame(updateHeaderScroll);
        return;
    }
    updateAppViewportHeight();
    requestAnimationFrame(() => {
        renderCards();
        updateHandScrollbar();
        updateHeaderScroll();
    });
}

function activeMenuContainsFocusedInput() {
    const active = document.activeElement;
    if (!active) {
        return false;
    }
    const openMenus = [menu, buttonMenu, favoriteMenu, interactionMenu, settingsMenu, openPickMenu]
        .filter(element => element && element.style.display === 'block');
    if (!openMenus.some(element => element.contains(active))) return false;
    return active.matches('input, select, textarea, button');
}

function isFullscreenActive() {
    return !!document.fullscreenElement;
}

function updateFullscreenButton() {
    if (!fullscreenButton) return;
    fullscreenButton.textContent = isFullscreenActive() ? 'X' : '[]';
    fullscreenButton.title = isFullscreenActive() ? t('fullscreen.exit') : t('fullscreen.enter');
}

async function toggleFullscreen() {
    try {
        if (isFullscreenActive()) {
            await document.exitFullscreen();
        } else if (document.documentElement.requestFullscreen) {
            await document.documentElement.requestFullscreen();
        }
    } catch (error) {
        console.warn('Fullscreen konnte nicht umgeschaltet werden:', error);
    } finally {
        updateFullscreenButton();
        refreshViewportLayout();
    }
}

function toggleSettingsHelp(topic) {
    const tooltip = document.getElementById('settings-tooltip');
    if (!tooltip) return;

    const texts = {
        view: t('settings.help_view'),
        drag: t('settings.help_drag'),
        players: t('settings.help_players')
    };

    const text = texts[topic] || '';
    if (tooltip.style.display === 'block' && tooltip.dataset.topic === topic) {
        hideSettingsHelp();
        return;
    }

    tooltip.dataset.topic = topic;
    tooltip.textContent = text;
    tooltip.style.display = 'block';
}

function hideSettingsHelp() {
    const tooltip = document.getElementById('settings-tooltip');
    if (!tooltip) return;
    tooltip.style.display = 'none';
    tooltip.dataset.topic = '';
}

function toggleActionHelp(topic) {
    const tooltip = document.getElementById('action-tooltip');
    if (!tooltip) return;

    const texts = {
        'play-table': t('action.help_play_table'),
        flip: t('action.help_flip'),
        'play-zone': t('action.help_play_zone'),
        give: t('action.help_give')
    };

    const text = texts[topic] || '';
    if (tooltip.style.display === 'block' && tooltip.dataset.topic === topic) {
        hideActionHelp();
        return;
    }

    tooltip.dataset.topic = topic;
    tooltip.textContent = text;
    tooltip.style.display = 'block';
}

function hideActionHelp() {
    const tooltip = document.getElementById('action-tooltip');
    if (!tooltip) return;
    tooltip.style.display = 'none';
    tooltip.dataset.topic = '';
}

backdrop.addEventListener('click', () => {
    if (!openPickMenuIsOpen()) closeAllMenus();
});
document.getElementById('action-cancel').addEventListener('click', closeMenu);
document.getElementById('button-menu-close').addEventListener('click', closeButtonMenu);
document.getElementById('mobile-button-normal').addEventListener('click', () => setMobileButtonAltClick(false));
document.getElementById('mobile-button-alt').addEventListener('click', () => setMobileButtonAltClick(true));
document.getElementById('favorite-close').addEventListener('click', closeFavoriteMenu);
document.getElementById('favorite-remove').addEventListener('click', removeActiveFavorite);
attachFavoriteButtonEvents(favoriteLeftButton, 'left');
attachFavoriteButtonEvents(favoriteRightButton, 'right');
actionAllToggle?.addEventListener('click', toggleActionMenuAllCards);
actionZoneLayoutButton?.addEventListener('click', toggleDropZoneSpreadCards);
handCountButton?.addEventListener('click', openMenuFromHandCount);
colorButton?.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
});
colorButton?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleColorDropdown();
});
colorDropdown?.addEventListener('click', (event) => event.stopPropagation());
interactionButton?.addEventListener('click', openInteractionMenu);
mobileButtonsButton?.addEventListener('click', openButtonMenu);
document.getElementById('settings-button').addEventListener('click', openSettings);
document.getElementById('settings-close').addEventListener('click', closeSettings);
document.getElementById('admin-sync-all-hands')?.addEventListener('click', requestAdminSyncAllHands);
document.getElementById('interaction-close').addEventListener('click', closeInteractionMenu);
document.getElementById('interaction-send').addEventListener('click', submitInteractionRequest);
document.getElementById('open-pick-confirm').addEventListener('click', confirmOpenPick);
document.getElementById('open-pick-cancel').addEventListener('click', cancelOpenPick);
cardZoomMenu?.addEventListener('pointerdown', startCardZoomDrag);
cardZoomMenu?.addEventListener('pointermove', moveCardZoomDrag);
cardZoomMenu?.addEventListener('pointerup', finishCardZoomDrag);
cardZoomMenu?.addEventListener('pointercancel', cancelCardZoomDrag);
cardZoomMenu?.addEventListener('click', (event) => {
    if (!cardZoomGuid) return;
    event.preventDefault();
    event.stopPropagation();
});
fullscreenButton?.addEventListener('click', toggleFullscreen);
statusIndicator?.addEventListener('click', showConnectionInfo);
updateFullscreenButton();

document.addEventListener('click', () => {
    closeColorDropdown();
    closePlayerTargetPickers();
});

document.addEventListener('fullscreenchange', () => {
    updateFullscreenButton();
    refreshViewportLayout(true);
});

window.addEventListener('orientationchange', () => refreshViewportLayout(true));
window.visualViewport?.addEventListener('resize', () => refreshViewportLayout(false));

document.querySelectorAll('input[name="view-mode"]').forEach(input => {
    input.addEventListener('change', () => {
        applyViewMode(input.value);
        localStorage.setItem(VIEW_MODE_STORAGE_KEY, input.value);
    });
});

document.querySelectorAll('input[name="drag-mode"]').forEach(input => {
    input.addEventListener('change', () => {
        applyDragModeSetting(input.value);
        localStorage.setItem(DRAG_MODE_STORAGE_KEY, input.value);
    });
});

document.querySelectorAll('input[name="player-filter"]').forEach(input => {
    input.addEventListener('change', () => {
        applyPlayerFilterSetting(input.value);
        localStorage.setItem(PLAYER_FILTER_STORAGE_KEY, input.value);
        buildColorDropdown();
        renderPlayerTargets();
    });
});

document.querySelectorAll('.settings-help').forEach(button => {
    button.addEventListener('click', () => {
        toggleSettingsHelp(button.dataset.help);
    });
});

document.querySelectorAll('.action-help').forEach(button => {
    button.addEventListener('click', () => {
        toggleActionHelp(button.dataset.help);
    });
});

document.getElementById('action-play-table').addEventListener('click', () => submitActionMenuAction('play_to_table'));
document.getElementById('action-flip').addEventListener('click', () => submitActionMenuAction('flip_cards'));
document.getElementById('action-play-zone').addEventListener('click', () => submitActionMenuAction('play_to_zone'));
document.getElementById('action-give').addEventListener('click', () => submitActionMenuAction('give_to_player'));

function renderPlayerTargets() {
    const targets = selectablePlayerColors().filter(color => color !== myColor);
    if (!targets.includes(giveTargetColor)) {
        giveTargetColor = targets[0] || "";
    }
    if (!targets.includes(interactionTargetColor)) {
        interactionTargetColor = targets[0] || "";
    }
    renderPlayerTargetPicker(
        'give-target',
        giveTargetColor,
        targets,
        (color) => {
            giveTargetColor = color;
            renderPlayerTargets();
        }
    );
    renderPlayerTargetPicker(
        'interaction-target',
        interactionTargetColor,
        targets,
        (color) => {
            interactionTargetColor = color;
            renderPlayerTargets();
        }
    );
}

function applyColorToOption(option, color) {
    option.style.color = colorMap[color] || '#fff';
}

function renderPlayerTargetPicker(prefix, selectedColor, targets, onSelect) {
    const picker = document.getElementById(`${prefix}-picker`);
    if (!picker) return;

    const targetPicker = createPlayerTargetPicker({
        selectedColor,
        targets,
        onSelect,
    });
    targetPicker.element.id = `${prefix}-picker`;
    picker.replaceWith(targetPicker.element);
}

function closePlayerTargetPickers(exceptPicker = null) {
    document.querySelectorAll('.player-target-picker.open').forEach(picker => {
        if (picker !== exceptPicker) {
            picker.classList.remove('open');
        }
    });
}

function renderZoneTargets() {
    const select = document.getElementById('zone-target');
    if (!select) return;
    const oldValue = select.value;
    const nextSelect = createDropZoneSelect({
        selectedValue: oldValue,
        valueMode: 'json',
    });
    nextSelect.id = 'zone-target';
    select.replaceWith(nextSelect);
}

function buildDropZoneTargetJson(targetValueOrZone, spreadCards) {
    let target = targetValueOrZone;
    if (typeof targetValueOrZone === 'string') {
        try {
            target = JSON.parse(targetValueOrZone);
        } catch (_) {
            return targetValueOrZone;
        }
    }
    if (!target || typeof target !== 'object') {
        return '';
    }
    const nextTarget = { ...target };
    if (spreadCards) {
        nextTarget.spread_cards = true;
    } else {
        delete nextTarget.spread_cards;
    }
    return JSON.stringify(nextTarget);
}

function finishFavoriteAssignment(closeFn) {
    if (typeof closeFn === 'function') {
        closeFn();
    }
    activeFavoriteSlot = null;
    renderFavoriteButtons();
}

function submitActionMenuAction(actionName) {
    const zoneTargetValue = document.getElementById('zone-target')?.value || '';
    const targetColor = giveTargetColor;

    if (activeMenuMode === 'favorite') {
        if (!activeFavoriteSlot) return;
        if (actionName === 'play_to_zone') {
            if (!zoneTargetValue) {
                alert(t('errors.no_drop_zones'));
                return;
            }
            let zone = null;
            try {
                zone = JSON.parse(zoneTargetValue);
            } catch (_) {
                zone = null;
            }
            if (!zone) {
                alert(t('errors.no_drop_zones'));
                return;
            }
            saveFavorite(activeFavoriteSlot, {
                type: 'drop_zone',
                key: dropZoneFavoriteKey(zone),
                label: zone.name || '?',
                target: zone,
                spread_cards: dropZoneSpreadCards,
            });
            finishFavoriteAssignment(closeMenu);
            return;
        }
        if (actionName === 'give_to_player' && !targetColor) {
            alert(t('errors.choose_target_player'));
            return;
        }
        saveFavorite(activeFavoriteSlot, {
            type: 'card_action',
            action: actionName,
            target_color: actionName === 'give_to_player' ? targetColor : null,
            label: cardActionFavoriteLabel({
                action: actionName,
                target_color: actionName === 'give_to_player' ? targetColor : null,
            }),
        });
        finishFavoriteAssignment(closeMenu);
        return;
    }

    if (actionName === 'play_to_zone') {
        if (!zoneTargetValue) {
            alert(t('errors.no_drop_zones'));
            return;
        }
        sendCardAction('play_to_zone', actionTargetGuids(), buildDropZoneTargetJson(zoneTargetValue, dropZoneSpreadCards));
        closeMenu();
        return;
    }
    if (actionName === 'give_to_player') {
        if (!targetColor) {
            alert(t('errors.choose_target_player'));
            return;
        }
        sendCardAction('give_to_player', actionTargetGuids(), targetColor);
        closeMenu();
        return;
    }
    sendCardAction(actionName, actionTargetGuids());
    closeMenu();
}

function renderMobileButtons() {
    const list = document.getElementById('mobile-button-list');
    if (!list) return;

    list.replaceChildren();

    if (mobileButtons.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'hint';
        empty.textContent = t('mobile_buttons.none_available');
        list.appendChild(empty);
        mobileButtonsButton.style.display = 'none';
        return;
    }

    mobileButtonsButton.style.display = 'inline-flex';

    mobileButtons.forEach(button => {
        const row = document.createElement('div');
        row.className = 'mobile-button-row';

        const actionButton = document.createElement('button');
        actionButton.type = 'button';
        actionButton.classList.toggle('favorite-save-choice', activeMenuMode === 'favorite');
        actionButton.textContent = button.name || '?';
        actionButton.addEventListener('click', () => {
            submitMobileButton(button);
        });
        row.appendChild(actionButton);

        const helpButton = document.createElement('button');
        helpButton.type = 'button';
        helpButton.className = 'mobile-button-help';
        helpButton.textContent = '?';
        helpButton.disabled = !button.tooltip;
        helpButton.addEventListener('click', () => {
            toggleButtonHelp(button.id, button.tooltip || '');
        });
        row.appendChild(helpButton);

        list.appendChild(row);
    });
}

function submitMobileButton(buttonData) {
    if (!buttonData) return;
    if (activeMenuMode === 'favorite') {
        if (!activeFavoriteSlot) return;
        saveFavorite(activeFavoriteSlot, {
            type: 'mobile_button',
            key: mobileButtonFavoriteKey(buttonData),
            button_id: buttonData.id,
            label: buttonData.name || '?',
            alt_click: mobileButtonAltClick,
        });
        finishFavoriteAssignment(closeButtonMenu);
        return;
    }
    sendMobileButtonAction(buttonData.id);
    closeButtonMenu();
}

function favoriteStorageKey(slot) {
    return `${FAVORITE_STORAGE_PREFIX}_${myColor}_${slot}`;
}

function loadFavorite(slot) {
    try {
        return JSON.parse(localStorage.getItem(favoriteStorageKey(slot)) || 'null');
    } catch (_) {
        return null;
    }
}

function saveFavorite(slot, favorite) {
    if (!slot || !favorite) return;
    localStorage.setItem(favoriteStorageKey(slot), JSON.stringify(favorite));
    renderFavoriteButtons();
}

function removeFavorite(slot) {
    if (!slot) return;
    localStorage.removeItem(favoriteStorageKey(slot));
    renderFavoriteButtons();
}

function dropZoneFavoriteKey(zone) {
    if (!zone) return '';
    return JSON.stringify({
        type: zone.type || '',
        object_guid: zone.object_guid || '',
        snap_index: zone.snap_index ?? '',
        name: zone.name || '',
        description: zone.description || '',
    });
}

function mobileButtonFavoriteKey(button) {
    return String(button?.id || '');
}

function knownUiPlayerColors() {
    return uniqueColors(playerColors.length ? playerColors : defaultPlayerColors);
}

function targetPlayerColors() {
    return selectablePlayerColors().filter(color => color !== myColor);
}

function favoriteTargetColors() {
    return targetPlayerColors();
}

function createSaveFavoriteButton(label, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'favorite-choice favorite-save-choice';
    button.textContent = label || '?';
    button.addEventListener('click', onClick);
    return button;
}

function createPlayerTargetPicker({ selectedColor = '', targets = targetPlayerColors(), onSelect = null } = {}) {
    const picker = document.createElement('div');
    picker.className = 'player-target-picker';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'player-target-button';
    button.textContent = selectedColor || t('player.no_target');
    applyColorToOption(button, selectedColor);
    button.disabled = targets.length === 0;

    const list = document.createElement('div');
    list.className = 'player-target-list';

    button.addEventListener('click', (event) => {
        event.stopPropagation();
        closePlayerTargetPickers(picker);
        picker.classList.toggle('open');
    });

    targets.forEach(color => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'player-target-option';
        option.textContent = color;
        applyColorToOption(option, color);
        option.addEventListener('click', (event) => {
            event.stopPropagation();
            selectedColor = color;
            button.textContent = selectedColor || t('player.no_target');
            applyColorToOption(button, selectedColor);
            if (onSelect) onSelect(color);
            closePlayerTargetPickers();
        });
        list.appendChild(option);
    });

    picker.appendChild(button);
    picker.appendChild(list);
    return {
        element: picker,
        getValue: () => selectedColor,
        setValue: (color) => {
            selectedColor = color || '';
            button.textContent = selectedColor || t('player.no_target');
            applyColorToOption(button, selectedColor);
        },
    };
}

function createDropZoneSelect({ selectedValue = '', valueMode = 'key' } = {}) {
    const select = document.createElement('select');
    dropZones.forEach(zone => {
        const key = dropZoneFavoriteKey(zone);
        const option = document.createElement('option');
        option.value = valueMode === 'json' ? JSON.stringify(zone) : key;
        option.textContent = zone.name || '?';
        select.appendChild(option);
    });
    if (selectedValue && Array.from(select.options).some(option => option.value === selectedValue)) {
        select.value = selectedValue;
    }
    select.disabled = select.options.length === 0;
    return select;
}

function createDropZoneLayoutButton(spreadCards, onToggle) {
    const layoutButton = document.createElement('button');
    layoutButton.type = 'button';
    layoutButton.className = 'zone-layout-toggle';
    layoutButton.classList.toggle('active', !!spreadCards);
    layoutButton.textContent = spreadCards ? '\u2194' : '\u25a3';
    layoutButton.title = spreadCards ? t('action.zone_layout_spread') : t('action.zone_layout_stack');
    layoutButton.setAttribute('aria-label', spreadCards ? t('action.zone_layout_spread_aria') : t('action.zone_layout_stack_aria'));
    layoutButton.setAttribute('aria-pressed', spreadCards ? 'true' : 'false');
    layoutButton.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (onToggle) onToggle();
    });
    return layoutButton;
}

function cardActionFavoriteLabel(favorite) {
    if (favorite.action === 'play_to_table') return t('action.play_table');
    if (favorite.action === 'flip_cards') return t('action.flip');
    if (favorite.action === 'give_to_player') {
        return t('favorite.action_give_to', {color: favorite.target_color || '?'});
    }
    return favorite.label || '?';
}

function interactionFavoriteLabel(favorite) {
    const typeLabel = favorite.interaction_type === 'pick_open'
        ? t('interaction.type_pick_open')
        : t('interaction.type_draw_hidden');
    return t('favorite.request_to', {
        color: favorite.target_color || '?',
        count: favorite.count || 1,
        type: typeLabel,
    });
}

function resolveFavorite(favorite) {
    if (!favorite || typeof favorite !== 'object') return null;
    if (favorite.type === 'card_action') {
        const action = favorite.action || '';
        const validActions = ['play_to_table', 'flip_cards', 'give_to_player'];
        if (!validActions.includes(action)) return null;
        if (action === 'give_to_player' && !knownUiPlayerColors().includes(favorite.target_color)) {
            return null;
        }
        return {
            ...favorite,
            label: cardActionFavoriteLabel(favorite),
        };
    }
    if (favorite.type === 'interaction_request') {
        if (!knownUiPlayerColors().includes(favorite.target_color)) return null;
        if (!['draw_random_hidden', 'pick_open'].includes(favorite.interaction_type)) return null;
        return {
            ...favorite,
            count: Math.max(1, Number(favorite.count || 1)),
            label: interactionFavoriteLabel(favorite),
        };
    }
    if (favorite.type === 'drop_zone') {
        const key = favorite.key || dropZoneFavoriteKey(favorite.target);
        const zone = dropZones.find(item => dropZoneFavoriteKey(item) === key);
        if (!zone) return null;
        return {
            ...favorite,
            key,
            label: zone.name || favorite.label || '?',
            target: zone,
            spread_cards: !!favorite.spread_cards,
        };
    }
    if (favorite.type === 'mobile_button') {
        const key = favorite.key || favorite.button_id;
        const button = mobileButtons.find(item => mobileButtonFavoriteKey(item) === key);
        if (!button) return null;
        return {
            ...favorite,
            key,
            button_id: button.id,
            label: button.name || favorite.label || '?',
            button,
            alt_click: !!favorite.alt_click,
        };
    }
    return null;
}

function currentFavorite(slot) {
    return resolveFavorite(loadFavorite(slot));
}

function renderFavoriteButtons() {
    renderFavoriteButton(favoriteLeftButton, 'left');
    renderFavoriteButton(favoriteRightButton, 'right');
}

function renderFavoriteButton(button, slot) {
    if (!button) return;
    const favorite = currentFavorite(slot);
    const unavailable = loadFavorite(slot) && !favorite;
    const disabledNeedsCards = ['drop_zone', 'card_action'].includes(favorite?.type) && selectedGuids.size === 0;
    button.classList.toggle('assigned', !!favorite);
    button.classList.toggle('unavailable', !!unavailable || !!disabledNeedsCards);
    const label = favorite
        ? t('favorite.assigned_aria', {slot: favoriteSlotLabel(slot), name: favorite.label})
        : t(slot === 'left' ? 'favorite.left_aria' : 'favorite.right_aria');
    button.setAttribute('aria-label', label);
    button.title = favorite ? favorite.label : t('favorite.empty_tap');
}

function favoriteSlotLabel(slot) {
    return slot === 'left' ? t('favorite.slot_left') : t('favorite.slot_right');
}

function attachFavoriteButtonEvents(button, slot) {
    if (!button) return;
    button.addEventListener('pointerdown', event => startFavoritePress(event, slot));
    button.addEventListener('pointermove', moveFavoritePress);
    button.addEventListener('pointerup', finishFavoritePress);
    button.addEventListener('pointercancel', cancelFavoritePress);
    button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
    });
}

function startFavoritePress(event, slot) {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    closeCardZoom();
    favoritePress = {
        slot,
        long: false,
        x: event.clientX,
        y: event.clientY,
        pointerId: event.pointerId,
        target: event.currentTarget,
        timer: null,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    favoritePress.timer = setTimeout(() => {
        if (!favoritePress) return;
        favoritePress.long = true;
        openFavoriteMenu(slot);
    }, LONG_PRESS_MS);
}

function moveFavoritePress(event) {
    if (!favoritePress) return;
    const distance = Math.hypot(event.clientX - favoritePress.x, event.clientY - favoritePress.y);
    if (distance > DRAG_THRESHOLD_PX) {
        cancelFavoritePress();
    }
}

function finishFavoritePress(event) {
    if (!favoritePress) return;
    event.preventDefault();
    event.stopPropagation();
    const press = favoritePress;
    clearTimeout(press.timer);
    favoritePress = null;
    if (!press.long) {
        executeFavorite(press.slot);
    }
}

function cancelFavoritePress() {
    if (!favoritePress) return;
    clearTimeout(favoritePress.timer);
    favoritePress = null;
}

function favoriteSelectedGuids() {
    return currentCards.map(card => card.guid).filter(guid => selectedGuids.has(guid));
}

function executeFavorite(slot) {
    const favorite = currentFavorite(slot);
    if (!favorite) {
        alert(t('favorite.empty_tap'));
        return;
    }
    if (favorite.type === 'drop_zone') {
        const guids = favoriteSelectedGuids();
        if (guids.length === 0) {
            alert(t('favorite.no_selected_cards'));
            return;
        }
        sendCardAction('play_to_zone', guids, buildDropZoneTargetJson(favorite.target, favorite.spread_cards));
        return;
    }
    if (favorite.type === 'card_action') {
        const guids = favoriteSelectedGuids();
        if (guids.length === 0) {
            alert(t('favorite.no_selected_cards'));
            return;
        }
        sendCardAction(favorite.action, guids, favorite.target_color || null);
        return;
    }
    if (favorite.type === 'interaction_request') {
        socket.emit('interaction_request', {
            color: myColor,
            target_color: favorite.target_color,
            interaction_type: favorite.interaction_type,
            count: favorite.count || 1,
        });
        return;
    }
    if (favorite.type === 'mobile_button') {
        sendMobileButtonAction(favorite.button_id, favorite.alt_click);
    }
}

function renderFavoriteMenu() {
    const list = document.getElementById('favorite-choice-list');
    const current = document.getElementById('favorite-current');
    const title = document.getElementById('favorite-title');
    if (!list || !current || !activeFavoriteSlot) return;

    const favorite = currentFavorite(activeFavoriteSlot);
    title.textContent = t('favorite.title_slot', {slot: favoriteSlotLabel(activeFavoriteSlot)});
    current.textContent = favorite
        ? t('favorite.current_label', {type: favoriteTypeLabel(favorite), name: favoriteCurrentName(favorite)})
        : t('favorite.current_empty');

    list.replaceChildren();
    list.appendChild(createFavoriteHubButton(t('favorite.card_actions'), () => {
        openMenu({mode: 'favorite'});
    }));
    list.appendChild(createFavoriteHubButton(t('favorite.requests'), () => {
        openInteractionMenu({mode: 'favorite'});
    }, favoriteTargetColors().length === 0));
    list.appendChild(createFavoriteHubButton(t('favorite.buttons'), () => {
        openButtonMenu({mode: 'favorite'});
    }, mobileButtons.length === 0));
}

function createFavoriteHubButton(label, onClick, disabled = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'favorite-choice favorite-save-choice';
    button.textContent = label || '?';
    button.disabled = !!disabled;
    button.addEventListener('click', onClick);
    return button;
}

function favoriteTypeLabel(favorite) {
    if (favorite?.type === 'drop_zone') return t('favorite.type_drop_zone');
    if (favorite?.type === 'mobile_button') return t('favorite.type_button');
    if (favorite?.type === 'card_action') return t('favorite.type_card_action');
    if (favorite?.type === 'interaction_request') return t('favorite.type_request');
    return t('favorite.type_unknown');
}

function favoriteCurrentName(favorite) {
    if (!favorite) return '';
    const mode = favoriteModeLabel(favorite);
    return mode ? `${favorite.label} (${mode})` : favorite.label;
}

function favoriteModeLabel(favorite) {
    if (favorite?.type === 'drop_zone') {
        return favorite.spread_cards ? t('favorite.layout_spread') : t('favorite.layout_stack');
    }
    if (favorite?.type === 'mobile_button') {
        return favorite.alt_click ? t('mobile_buttons.alt_click') : t('mobile_buttons.normal');
    }
    if (favorite?.type === 'interaction_request') {
        return `${favorite.count || 1}`;
    }
    return '';
}

function removeActiveFavorite() {
    if (!activeFavoriteSlot) return;
    removeFavorite(activeFavoriteSlot);
    closeFavoriteMenu();
}

function toggleButtonHelp(buttonId, text) {
    const tooltip = document.getElementById('button-tooltip');
    if (!tooltip || !text) return;

    if (tooltip.style.display === 'block' && tooltip.dataset.buttonId === buttonId) {
        hideButtonHelp();
        return;
    }

    tooltip.dataset.buttonId = buttonId;
    tooltip.textContent = text;
    tooltip.style.display = 'block';
}

function hideButtonHelp() {
    const tooltip = document.getElementById('button-tooltip');
    if (!tooltip) return;
    tooltip.style.display = 'none';
    tooltip.dataset.buttonId = '';
}

function setMobileButtonAltClick(enabled) {
    mobileButtonAltClick = !!enabled;
    updateMobileButtonModeButtons();
    hideButtonHelp();
}

function updateMobileButtonModeButtons() {
    const normalButton = document.getElementById('mobile-button-normal');
    const altButton = document.getElementById('mobile-button-alt');
    if (!normalButton || !altButton) return;
    normalButton.classList.toggle('active', !mobileButtonAltClick);
    altButton.classList.toggle('active', mobileButtonAltClick);
}

function updateInteractionButtonState() {
    if (!interactionButton) return;
    const hasPending = incomingInteractions.length > 0;
    interactionButton.classList.toggle('has-pending', hasPending);
    interactionButton.setAttribute(
        'aria-label',
        hasPending ? t('interaction.pending_aria', {count: incomingInteractions.length}) : t('aria.player_actions')
    );
}

function interactionTypeLabel(type) {
    if (type === 'draw_random_hidden') return t('interaction.type_draw_hidden');
    if (type === 'pick_open') return t('interaction.type_pick_open');
    return t('interaction.type_generic');
}

function renderInteractions() {
    renderInteractionList(
        document.getElementById('incoming-interactions'),
        incomingInteractions,
        true
    );
    renderInteractionList(
        document.getElementById('outgoing-interactions'),
        outgoingInteractions,
        false
    );
    updateInteractionButtonState();
}

function renderInteractionList(list, requests, incoming) {
    if (!list) return;
    list.replaceChildren();

    if (!requests.length) {
        const empty = document.createElement('div');
        empty.className = 'hint';
        empty.textContent = incoming ? t('interaction.no_incoming') : t('interaction.no_outgoing');
        list.appendChild(empty);
        return;
    }

    requests.forEach(requestData => {
        const row = document.createElement('div');
        row.className = 'interaction-card';
        const canReopenSelection = !incoming && requestData.status === 'selecting';
        row.classList.toggle('selecting', canReopenSelection);
        if (canReopenSelection) {
            row.addEventListener('click', () => openSelectionRequest(requestData.id));
        }

        const text = document.createElement('div');
        text.className = 'interaction-card-text';
        const title = document.createElement('strong');
        title.textContent = incoming
            ? t('interaction.incoming_title', {
                color: requestData.from_color,
                count: requestData.count,
                type: interactionTypeLabel(requestData.type),
            })
            : t('interaction.outgoing_title', {
                color: requestData.target_color,
                count: requestData.count,
                type: interactionTypeLabel(requestData.type),
            });
        const status = document.createElement('span');
        status.textContent = incoming
            ? t('interaction.status_confirmation_required')
            : (requestData.status === 'selecting' ? t('interaction.status_selecting') : t('interaction.status_waiting'));
        text.appendChild(title);
        text.appendChild(status);
        row.appendChild(text);

        if (incoming) {
            const accept = document.createElement('button');
            accept.type = 'button';
            accept.className = 'primary';
            accept.textContent = t('common.ok');
            accept.addEventListener('click', () => respondInteraction(requestData.id, true));
            row.appendChild(accept);

            const deny = document.createElement('button');
            deny.type = 'button';
            deny.className = 'danger';
            deny.textContent = t('common.no');
            deny.addEventListener('click', () => respondInteraction(requestData.id, false));
            row.appendChild(deny);
        } else {
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'secondary';
            cancel.textContent = t('common.stop');
            cancel.addEventListener('click', (event) => {
                event.stopPropagation();
                cancelInteraction(requestData.id);
            });
            row.appendChild(cancel);
        }

        list.appendChild(row);
    });
}

function submitInteractionRequest() {
    const target = interactionTargetColor;
    const interactionType = document.getElementById('interaction-type').value;
    const count = Number(document.getElementById('interaction-count').value || 1);
    if (!target) {
        alert(t('errors.choose_other_player'));
        return;
    }
    if (activeMenuMode === 'favorite') {
        if (!activeFavoriteSlot) return;
        const favorite = {
            target_color: target,
            interaction_type: interactionType,
            count,
        };
        saveFavorite(activeFavoriteSlot, {
            type: 'interaction_request',
            ...favorite,
            label: interactionFavoriteLabel(favorite),
        });
        finishFavoriteAssignment(closeInteractionMenu);
        return;
    }
    socket.emit('interaction_request', {
        color: myColor,
        target_color: target,
        interaction_type: interactionType,
        count,
    });
}

function respondInteraction(requestId, accepted) {
    socket.emit('interaction_response', {
        color: myColor,
        request_id: requestId,
        accepted,
    });
}

function cancelInteraction(requestId) {
    socket.emit('interaction_cancel', {
        color: myColor,
        request_id: requestId,
    });
}

function openSelectionRequest(requestId) {
    socket.emit('interaction_open_selection_request', {
        color: myColor,
        request_id: requestId,
    });
}

function renderOpenPick() {
    const list = document.getElementById('open-pick-list');
    const countLabel = document.getElementById('open-pick-count');
    const info = document.getElementById('open-pick-info');
    if (!list || !activeOpenPick) return;

    const requestData = activeOpenPick.request || {};
    const hiddenSelection = requestData.type === 'draw_random_hidden';
    const heading = document.querySelector('#open-pick-menu h2');
    if (heading) heading.textContent = hiddenSelection ? t('open_pick.hidden_title') : t('open_pick.open_title');
    countLabel.textContent = `${openPickSelectedGuids.size}/${requestData.count || 0}`;
    info.textContent = hiddenSelection
        ? t('open_pick.hidden_info', {color: requestData.target_color || '?', count: requestData.count || 0})
        : t('open_pick.open_info', {color: requestData.target_color || '?', count: requestData.count || 0});
    list.replaceChildren();

    const visibleCards = activeOpenPick.cards.map(card => (
        hiddenSelection
            ? {
                ...card,
                face_down: true,
                image: card.back_image || '',
                card_index: null,
                atlas_width: 1,
                atlas_height: 1,
                attached_decals: [],
            }
            : { ...card, face_down: false }
    ));

    getDisplayCardsForList(visibleCards).forEach(visibleCard => {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        cardDiv.dataset.guid = visibleCard.guid;
        cardDiv.classList.toggle('selected', openPickSelectedGuids.has(visibleCard.guid));
        applyTTSCardSize(cardDiv, visibleCard, 'open-pick');

        const imageElement = createCardImage(visibleCard, 'open-pick');
        const title = document.createElement('div');
        title.className = 'card-title';
        title.textContent = hiddenSelection ? '' : (visibleCard.name || '');
        if (!title.textContent) title.style.display = 'none';
        imageElement.appendChild(title);
        cardDiv.appendChild(imageElement);

        cardDiv.addEventListener('click', () => toggleOpenPickCard(visibleCard.guid));
        list.appendChild(cardDiv);
    });
}

function toggleOpenPickCard(guid) {
    if (!activeOpenPick || !guid) return;
    const maxCount = Number(activeOpenPick.request?.count || 0);
    if (openPickSelectedGuids.has(guid)) {
        openPickSelectedGuids.delete(guid);
    } else {
        if (openPickSelectedGuids.size >= maxCount) return;
        openPickSelectedGuids.add(guid);
    }
    updateOpenPickSelectionState();
}

function updateOpenPickSelectionState() {
    const countLabel = document.getElementById('open-pick-count');
    const requestData = activeOpenPick?.request || {};
    if (countLabel) {
        countLabel.textContent = `${openPickSelectedGuids.size}/${requestData.count || 0}`;
    }
    document.querySelectorAll('#open-pick-list .card').forEach(card => {
        card.classList.toggle('selected', openPickSelectedGuids.has(card.dataset.guid));
    });
}

function confirmOpenPick() {
    if (!activeOpenPick) return;
    const requestData = activeOpenPick.request || {};
    const guids = [...openPickSelectedGuids];
    if (guids.length !== Number(requestData.count || 0)) {
        alert(t('errors.pick_exact_count'));
        return;
    }
    socket.emit('interaction_pick_cards', {
        color: myColor,
        request_id: requestData.id,
        guids,
    });
    activeOpenPick = null;
    openPickSelectedGuids = new Set();
    closeOpenPickMenu();
}

function cancelOpenPick() {
    if (activeOpenPick?.request?.id) {
        cancelInteraction(activeOpenPick.request.id);
    }
    activeOpenPick = null;
    openPickSelectedGuids = new Set();
    closeOpenPickMenu();
}

function sendCardAction(action, guids, target = null) {
    if (!guids || guids.length === 0) return;
    socket.emit('card_action', { color: myColor, action, guids, target });
}

function sendMobileButtonAction(buttonId, altClick = mobileButtonAltClick) {
    if (!buttonId) return;
    socket.emit('mobile_button_action', { color: myColor, button_id: buttonId, alt_click: !!altClick });
}

container.addEventListener('scroll', updateHandScrollbar);

function headerScrollAxis() {
    return isPortrait() ? 'x' : 'y';
}

function headerHasOverflow() {
    if (!headerContent) return false;
    return headerScrollAxis() === 'x'
        ? headerContent.scrollWidth - headerContent.clientWidth > 2
        : headerContent.scrollHeight - headerContent.clientHeight > 2;
}

function updateHeaderScroll() {
    if (!headerContent || headerHasOverflow()) return;
    headerContent.scrollLeft = 0;
    headerContent.scrollTop = 0;
}

headerContent?.addEventListener('pointerdown', (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    if (!headerHasOverflow()) return;

    headerScrollDragging = true;
    headerScrollMoved = false;
    headerScrollStart = {
        x: event.clientX,
        y: event.clientY,
        scrollLeft: headerContent.scrollLeft,
        scrollTop: headerContent.scrollTop,
    };
    headerContent.classList.add('header-dragging');
    headerContent.setPointerCapture(event.pointerId);
});

headerContent?.addEventListener('pointermove', (event) => {
    if (!headerScrollDragging || !headerScrollStart) return;

    const dx = event.clientX - headerScrollStart.x;
    const dy = event.clientY - headerScrollStart.y;
    const axis = headerScrollAxis();
    const distance = axis === 'x' ? Math.abs(dx) : Math.abs(dy);

    if (distance > DRAG_THRESHOLD_PX) {
        headerScrollMoved = true;
    }

    if (axis === 'x') {
        headerContent.scrollLeft = headerScrollStart.scrollLeft - dx;
    } else {
        headerContent.scrollTop = headerScrollStart.scrollTop - dy;
    }

    if (headerScrollMoved) {
        event.preventDefault();
    }
});

function finishHeaderScroll() {
    headerScrollDragging = false;
    headerScrollStart = null;
    headerContent?.classList.remove('header-dragging');
}

headerContent?.addEventListener('pointerup', finishHeaderScroll);
headerContent?.addEventListener('pointercancel', finishHeaderScroll);
headerContent?.addEventListener('click', (event) => {
    if (!headerScrollMoved) return;
    event.preventDefault();
    event.stopPropagation();
    headerScrollMoved = false;
}, true);

handScrollbar.addEventListener('pointerdown', (event) => {
    scrollbarDragging = true;
    const thumbRect = handScrollbarThumb.getBoundingClientRect();
    const pointerIsOnThumb =
        event.clientX >= thumbRect.left &&
        event.clientX <= thumbRect.right &&
        event.clientY >= thumbRect.top &&
        event.clientY <= thumbRect.bottom;
    scrollbarDragOffsetX = pointerIsOnThumb
        ? event.clientX - thumbRect.left
        : (handScrollbarThumb.offsetWidth || 40) / 2;
    handScrollbar.setPointerCapture(event.pointerId);
    event.preventDefault();
    scrollHandFromScrollbar(event.clientX);
});

handScrollbar.addEventListener('pointermove', (event) => {
    if (!scrollbarDragging) return;
    scrollHandFromScrollbar(event.clientX);
});

handScrollbar.addEventListener('pointerup', () => {
    scrollbarDragging = false;
    scrollbarDragOffsetX = null;
});

handScrollbar.addEventListener('pointercancel', () => {
    scrollbarDragging = false;
    scrollbarDragOffsetX = null;
});

window.addEventListener('resize', () => refreshViewportLayout(false));

function updateHandScrollbar() {
    container.classList.remove('no-overflow');

    const maxScroll = container.scrollWidth - container.clientWidth;
    const hasOverflow = maxScroll > 2;

    container.classList.toggle('no-overflow', !hasOverflow);

    if (!hasOverflow) {
        handScrollbar.style.display = 'none';
        container.scrollLeft = 0;
        return;
    }

    handScrollbar.style.display = 'block';

    const trackWidth = handScrollbar.clientWidth - 12;
    const thumbWidth = Math.max(36, container.clientWidth / container.scrollWidth * trackWidth);
    const maxThumbLeft = trackWidth - thumbWidth;
    const thumbLeft = (container.scrollLeft / maxScroll) * maxThumbLeft;

    handScrollbarThumb.style.width = `${thumbWidth}px`;
    handScrollbarThumb.style.transform = `translateX(${thumbLeft}px)`;
}

function scrollHandFromScrollbar(clientX) {
    const rect = handScrollbar.getBoundingClientRect();
    const trackPadding = 6;
    const trackLeft = rect.left + trackPadding;
    const trackWidth = rect.width - trackPadding * 2;
    const thumbWidth = handScrollbarThumb.offsetWidth || 40;
    const maxThumbLeft = Math.max(1, trackWidth - thumbWidth);

    const pointerOffset = scrollbarDragOffsetX ?? thumbWidth / 2;
    let thumbLeft = clientX - trackLeft - pointerOffset;
    thumbLeft = clamp(thumbLeft, 0, maxThumbLeft);

    const maxScroll = container.scrollWidth - container.clientWidth;
    container.scrollLeft = (thumbLeft / maxThumbLeft) * maxScroll;
}

function applyViewMode(mode) {
    const normalized = mode === 'grid' ? 'grid' : 'overlap';

    document.body.classList.toggle('view-overlap', normalized === 'overlap');
    document.body.classList.toggle('view-grid', normalized === 'grid');

    document.querySelectorAll('input[name="view-mode"]').forEach(input => {
        input.checked = input.value === normalized;
    });

    renderCards();
    updateHandScrollbar();
    setTimeout(updateHandScrollbar, 0);
}

function normalizeDragMode(mode) {
    return ['auto', 'swap', 'move'].includes(mode) ? mode : 'auto';
}

function applyDragModeSetting(mode) {
    const normalized = normalizeDragMode(mode);

    document.querySelectorAll('input[name="drag-mode"]').forEach(input => {
        input.checked = input.value === normalized;
    });
}

function applyPlayerFilterSetting(mode) {
    const normalized = normalizePlayerFilter(mode);

    document.querySelectorAll('input[name="player-filter"]').forEach(input => {
        input.checked = input.value === normalized;
    });
}

function getActiveDragMode() {
    const configured = normalizeDragMode(
        document.querySelector('input[name="drag-mode"]:checked')?.value || 'auto'
    );

    if (configured !== 'auto') {
        return configured;
    }

    return isPortrait() ? 'swap' : 'move';
}

function getResponsiveCardSize(card, layoutContext = 'hand') {
    const scaleX = Number(card.scale_x || 1);
    const scaleZ = Number(card.scale_z || 1);

    let width = TTS_CARD_BASE_WIDTH * scaleX;
    let height = TTS_CARD_BASE_HEIGHT * scaleZ;

    if (card.sideways) {
        const tmp = width;
        width = height;
        height = tmp;
    }

    width = clamp(width, 95, 230);
    height = clamp(height, 120, 320);

    const maxHeight = layoutContext === 'open-pick'
        ? getMaxOpenPickCardImageHeight()
        : getMaxResponsiveCardImageHeight();
    if (height > maxHeight) {
        const factor = maxHeight / height;
        width = Math.max(1, width * factor);
        height = maxHeight;
    }

    return { width, imageHeight: height };
}

function getMaxResponsiveCardImageHeight() {
    const handArea = document.querySelector('.hand-area');
    const handAreaRect = handArea?.getBoundingClientRect();
    const handAreaLayoutHeight = handArea?.clientHeight || getVisibleViewportHeight();
    const visibleHandAreaHeight = handAreaRect
        ? Math.max(1, getVisibleViewportHeight() - Math.max(0, handAreaRect.top))
        : handAreaLayoutHeight;
    const handAreaHeight = Math.min(handAreaLayoutHeight, visibleHandAreaHeight);
    const containerStyle = getComputedStyle(container);
    const scrollbarStyle = getComputedStyle(handScrollbar);
    const safeSpacer = document.querySelector('.safe-bottom-spacer');

    const containerPaddingY =
        parseCssPx(containerStyle.paddingTop) +
        parseCssPx(containerStyle.paddingBottom);
    const scrollbarBlock =
        parseCssPx(scrollbarStyle.height) +
        parseCssPx(scrollbarStyle.marginTop) +
        parseCssPx(scrollbarStyle.marginBottom);
    const safeBottom = safeSpacer?.offsetHeight || 0;
    const rowCount = isPortrait() ? Math.min(2, Math.max(1, currentCards.length)) : 1;
    const rowGap = isPortrait() && rowCount > 1 ? parseCssPx(containerStyle.rowGap) : 0;
    const availableHeight =
        handAreaHeight -
        scrollbarBlock -
        safeBottom -
        containerPaddingY -
        rowGap -
        CARD_LAYOUT_RESERVE_PX;
    const rowHeight = availableHeight / rowCount;

    return Math.max(
        MIN_RESPONSIVE_CARD_IMAGE_HEIGHT,
        rowHeight - CARD_VERTICAL_CHROME_PX
    );
}

function getMaxOpenPickCardImageHeight() {
    const list = document.getElementById('open-pick-list');
    if (!list) return getMaxResponsiveCardImageHeight();

    const listStyle = getComputedStyle(list);
    const listRect = list.getBoundingClientRect();
    const visibleListHeight = Math.max(
        1,
        Math.min(
            list.clientHeight || listRect.height || getVisibleViewportHeight(),
            getVisibleViewportHeight() - Math.max(0, listRect.top)
        )
    );
    const paddingY =
        parseCssPx(listStyle.paddingTop) +
        parseCssPx(listStyle.paddingBottom);
    const rowCount = isPortrait()
        ? Math.min(2, Math.max(1, activeOpenPick?.cards?.length || 1))
        : 1;
    const rowGap = isPortrait() && rowCount > 1 ? parseCssPx(listStyle.rowGap) : 0;
    const availableHeight = visibleListHeight - paddingY - rowGap - 8;
    const rowHeight = availableHeight / rowCount;

    return Math.max(
        MIN_RESPONSIVE_CARD_IMAGE_HEIGHT,
        rowHeight - CARD_VERTICAL_CHROME_PX
    );
}

function applyTTSCardSize(cardDiv, card, layoutContext = 'hand') {
    const size = getResponsiveCardSize(card, layoutContext);

    cardDiv.style.width = `${size.width}px`;
    cardDiv.dataset.imageHeight = String(size.imageHeight);
}

function createCardImage(card, layoutContext = 'hand') {
    const showBack = card.face_down && card.back_image;

    if (showBack) {
        card = {
            ...card,
            image: card.back_image,
            atlas_width: 1,
            atlas_height: 1,
            card_index: null,
            attached_decals: []
        };
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'card-img';
    wrapper.style.position = 'relative';
    wrapper.style.overflow = 'hidden';

    applyImageHeight(wrapper, card, layoutContext);

    wrapper.appendChild(createBaseImageLayer(card));
    addDecalLayers(wrapper, card);

    return wrapper;
}

function createBaseImageLayer(card) {
    const layer = document.createElement('div');

    layer.style.position = 'absolute';
    layer.style.inset = '0';
    layer.style.backgroundRepeat = 'no-repeat';
    layer.style.backgroundPosition = 'center';
    layer.style.backgroundColor = '#2c2c2c';

    if (!card.image) {
        layer.textContent = '🃏';
        layer.style.display = 'flex';
        layer.style.alignItems = 'center';
        layer.style.justifyContent = 'center';
        layer.style.fontSize = '2rem';
        return layer;
    }

    if (
        card.card_index !== undefined &&
        card.card_index !== null &&
        card.atlas_width &&
        card.atlas_height &&
        Number(card.atlas_width) * Number(card.atlas_height) > 1
    ) {
        const atlasWidth = Number(card.atlas_width);
        const atlasHeight = Number(card.atlas_height);
        const zeroBasedIndex = Number(card.card_index);

        const col = zeroBasedIndex % atlasWidth;
        const row = Math.floor(zeroBasedIndex / atlasWidth);

        layer.style.backgroundImage = `url("${card.image}")`;
        layer.style.backgroundSize = `${atlasWidth * 100}% ${atlasHeight * 100}%`;

        const posX = atlasWidth <= 1 ? 0 : (col / (atlasWidth - 1)) * 100;
        const posY = atlasHeight <= 1 ? 0 : (row / (atlasHeight - 1)) * 100;

        layer.style.backgroundPosition = `${posX}% ${posY}%`;
        return layer;
    }

    layer.style.backgroundImage = `url("${card.image}")`;
    layer.style.backgroundSize = 'contain';
    return layer;
}

function addDecalLayers(wrapper, card) {
    normalizeDecals(card.attached_decals).forEach(decal => {
        const custom = decal.CustomDecal || {};
        const url = custom.ImageURL;

        if (!url) return;

        const decalLayer = document.createElement('img');
        decalLayer.src = url;
        decalLayer.alt = '';
        decalLayer.draggable = false;

        decalLayer.style.position = 'absolute';
        decalLayer.style.objectFit = 'contain';
        decalLayer.style.pointerEvents = 'none';
        decalLayer.style.transformOrigin = 'center center';

        applyDecalTransform(decalLayer, decal);
        wrapper.appendChild(decalLayer);
    });
}

function normalizeDecals(attachedDecals) {
    if (!attachedDecals) return [];
    if (Array.isArray(attachedDecals)) return attachedDecals;
    if (typeof attachedDecals === 'object') return Object.values(attachedDecals);
    return [];
}

function applyDecalTransform(element, decal) {
    const t = decal.Transform || {};

    const posX = Number(t.posX || 0);
    const posZ = Number(t.posZ || 0);
    const scaleX = Math.abs(Number(t.scaleX || 1));
    const scaleZ = Math.abs(Number(t.scaleZ || 1));
    const rotX = Number(t.rotX || 0);
    const rotY = Number(t.rotY || 0);
    const rotZ = Number(t.rotZ || 0);

    const centerX = 50 + posX * DECAL_POSITION_FACTOR_X;
    const centerY = 50 - posZ * DECAL_POSITION_FACTOR_Y;
    const widthPercent = clamp(scaleX * DECAL_SIZE_FACTOR_X, 5, 250);
    const heightPercent = clamp(scaleZ * DECAL_SIZE_FACTOR_Y, 5, 250);

    element.style.left = `${centerX}%`;
    element.style.top = `${centerY}%`;
    element.style.width = `${widthPercent}%`;
    element.style.height = `${heightPercent}%`;
    element.style.transform = `translate(-50%, -50%) rotate(${getDecalCssRotation(rotX, rotY, rotZ)}deg)`;
}

function getDecalCssRotation(rotX, rotY, rotZ) {
    let rotation = rotY + DECAL_ROTATION_OFFSET;

    if (Math.abs(rotY) < 0.001 && Math.abs(rotZ) > 0.001) {
        rotation = rotZ + DECAL_ROTATION_OFFSET;
    }

    return normalizeDegrees(rotation);
}

function applyImageHeight(element, card, layoutContext = 'hand') {
    element.style.height = `${getResponsiveCardSize(card, layoutContext).imageHeight}px`;
}

function normalizeDegrees(deg) {
    let result = deg % 360;
    if (result < 0) result += 360;
    return result;
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function parseCssPx(value) {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
}
