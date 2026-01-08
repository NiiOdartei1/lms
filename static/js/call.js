// static/js/call.js (cleaned up version)
// ===== Initialize Socket.IO =====
if (typeof io !== 'function') {
  console.error('Socket.IO not loaded');
}
const socket = io();

// ===== DOM Elements (defensive - use functions to always get fresh references) =====
function getCallModal() { return document.getElementById('callModal'); }
function getIncomingCallUI() { return document.getElementById('incomingCallUI'); }
function getActiveCallUI() { return document.getElementById('activeCallUI'); }
function getCallerName() { return document.getElementById('callerName'); }
function getCallerAvatar() { return document.getElementById('callerAvatar'); }
function getEndCallBtn() { return document.getElementById('endCallBtn'); }
function getMuteCallBtn() { return document.getElementById('muteCallBtn'); }
function getCallVideoContainer() { return document.getElementById('callVideoContainer'); }
function getStartCallBtn() { return document.getElementById('startCallBtn'); }

// For backwards compatibility, also create cached references
const callModal = getCallModal();
const incomingCallUI = getIncomingCallUI();
const activeCallUI = getActiveCallUI();
const callerNameEl = getCallerName();
const callerAvatarEl = getCallerAvatar();
const endCallBtn = getEndCallBtn();
const muteCallBtn = getMuteCallBtn();
const callVideoContainer = getCallVideoContainer();
const startCallBtn = getStartCallBtn();
const CURRENT_USER_ID = document.getElementById('current-user-id')?.value;

if (!CURRENT_USER_ID) {
  console.error('Missing current-user-id');
}

// Floating widget stubs
function showFloatingCall(/*callerName, avatarUrl*/) { /* no-op */ }
function hideFloatingCall() { /* no-op */ }

// ===== Ringtone =====
let ringtone = document.getElementById('ringtone');
if (!ringtone) {
    ringtone = document.createElement('audio');
    ringtone.id = 'ringtone';
    ringtone.src = '/static/sounds/ringtone.mp3';
    ringtone.loop = true;
    document.body.appendChild(ringtone);
}

// ===== Call State =====
let localStream = null;
let peerConnections = {};
let pendingIceCandidates = {};
let pendingOffers = {};
let currentCallTarget = null;

// ===== Helpers =====
async function initLocalAudio() {
    if (!localStream) {
        try {
            localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            console.error('Failed to get audio stream:', err);
            alert('Could not access microphone. Please check permissions and refresh the page.');
        }
    }
}

// ===== CENTRALIZED: Call Button State Manager =====
function updateCallButtonState() {
    if (!startCallBtn) return;

    const convIdEl = document.getElementById('current-conversation-id');
    const convTypeEl = document.getElementById('current-conversation-type');
    const targetPubIdEl = document.getElementById('current-conversation-target');

    const convId = convIdEl?.value || '';
    const convType = convTypeEl?.value || '';
    const targetPubId = targetPubIdEl?.value || '';

    // Enable only for DMs (direct conversations) with both convId and targetPubId
    const canCall = convId && (convType === 'dm' || convType === 'direct') && targetPubId;

    if (canCall) {
        startCallBtn.disabled = false;
        startCallBtn.style.opacity = '1';
        startCallBtn.style.cursor = 'pointer';
        startCallBtn.style.background = '#22c55e';
    } else {
        startCallBtn.disabled = true;
        startCallBtn.style.opacity = '0.5';
        startCallBtn.style.cursor = 'not-allowed';
        startCallBtn.style.background = '#94a3b8';
    }

    console.log('🔴 updateCallButtonState():', {
        convId: convId || '(empty)',
        convType: convType || '(empty)',
        targetPubId: targetPubId || '(empty)',
        canCall,
        convIdEl: convIdEl ? 'exists' : 'MISSING',
        convTypeEl: convTypeEl ? 'exists' : 'MISSING',
        targetPubIdEl: targetPubIdEl ? 'exists' : 'MISSING'
    });
}

// ===== SETUP: Wire Call Button to Conversation Selection =====
function setupCallButtonLogic() {
    // Prevent duplicate setup
    if (window.callButtonLogicSetup) return;
    window.callButtonLogicSetup = true;
    // Listen to hidden input changes
    const convIdInput = document.getElementById('current-conversation-id');
    const convTypeInput = document.getElementById('current-conversation-type');
    const convTargetInput = document.getElementById('current-conversation-target');

    if (!convIdInput || !convTypeInput || !convTargetInput) {
        console.warn('Hidden conversation inputs not found; retrying...');
        setTimeout(setupCallButtonLogic, 500);
        return;
    }

    // Update on input/change events
    [convIdInput, convTypeInput, convTargetInput].forEach(input => {
        input.addEventListener('input', updateCallButtonState);
        input.addEventListener('change', updateCallButtonState);
    });

    // Update on conversation selection (from chat.js click handler)
    const conversationList = document.getElementById('conversationList');
    if (conversationList) {
        conversationList.addEventListener('click', (e) => {
            const convItem = e.target.closest('.conv-item');
            if (!convItem) return;

            // Try to read from data attributes first, fallback to extracting from hidden inputs later
            const convId = convItem.dataset.conversationId;
            const convType = convItem.dataset.conversationType;
            const targetPubId = convItem.dataset.targetPublicId;
            const title = convItem.querySelector('.conv-title')?.innerText;

            console.log('🔵 Conversation clicked:', {
                convId, convType, targetPubId, title,
                note: 'Data attrs undefined? chat.js probably sets hidden inputs instead'
            });

            // Delay to allow chat.js to set hidden inputs
            setTimeout(() => {
                console.log('🟡 After 100ms delay, checking hidden inputs...');
                updateCallButtonState();
            }, 100);
        });
    }

    // Initial check
    updateCallButtonState();

    console.log('Call button logic initialized');
}

// ===== Start Call Handler =====
if (startCallBtn) {
    startCallBtn.addEventListener('click', async () => {
        const convId = document.getElementById('current-conversation-id')?.value;
        const convType = document.getElementById('current-conversation-type')?.value;
        const targetPubId = document.getElementById('current-conversation-target')?.value;
        const activeConv = document.querySelector('.conv-item.active');
        const targetName = activeConv?.querySelector('.conv-title')?.innerText || 'Unknown';

        if (!convId || !targetPubId) {
            console.warn('Missing conversation or target data');
            return;
        }

        if (convType === 'group') {
            alert('Group calls are not supported yet');
            return;
        }

        await startOutgoingCallUI(targetName, targetPubId, convId);
    });
}

// ===== End Call Handler =====
if (endCallBtn) {
    endCallBtn.addEventListener('click', () => {
        const convId = document.getElementById('current-conversation-id')?.value;
        if (currentCallTarget) {
            endCall(currentCallTarget, convId);
        }
    });
}

// ===== Peer Connection Factory =====
function createPeerConnection(pubId, conversationId) {
  const pc = new RTCPeerConnection({
    iceServers: [
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'stun:stun1.l.google.com:19302' }
    ]
  });

  if (localStream) {
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
  }

  const remoteAudio = document.createElement('audio');
  remoteAudio.autoplay = true;
  pc.ontrack = (ev) => {
    remoteAudio.srcObject = ev.streams[0];
    if (callVideoContainer) {
      callVideoContainer.innerHTML = '';
      callVideoContainer.appendChild(remoteAudio);
    }
  };

  pc.onicecandidate = (event) => {
    if (event.candidate && socket) {
      socket.emit('call_signal', {
        conversation_id: conversationId,
        to_public_id: pubId,
        signal_type: 'ice',
        signal_data: event.candidate
      });
    }
  };

  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'connected') {
      console.log('Peer connected:', pubId);
    } else if (['disconnected', 'failed', 'closed'].includes(pc.connectionState)) {
      try { peerConnections[pubId].close(); } catch(e){}
      delete peerConnections[pubId];
      delete pendingIceCandidates[pubId];
      const m = getCallModal();
      if (m) m.style.display = 'none';
      currentCallTarget = null;
    }
  };

  return pc;
}

// ===== Incoming Call UI =====
function showIncomingCall(fromName, fromPubId, conversationId, avatarUrl = '') {
    const safeName = (typeof fromName === 'string' && fromName.length) ? fromName : 'Unknown';
    const initial = (safeName && safeName.charAt) ? safeName.charAt(0) : '?';

    currentCallTarget = fromPubId || null;

    const callerName = getCallerName();
    const callerAvatar = getCallerAvatar();
    const incomingUI = getIncomingCallUI();
    const activeUI = getActiveCallUI();
    const endBtn = getEndCallBtn();
    const muteBtn = getMuteCallBtn();
    const modal = getCallModal();

    if (callerName) callerName.innerText = safeName;
    if (callerAvatar) {
      callerAvatar.src = avatarUrl ||
        `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect fill='%2364748b' width='80' height='80'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='white' font-size='32'%3E${encodeURIComponent(initial)}%3C/text%3E%3C/svg%3E`;
    }

    if (incomingUI) incomingUI.style.display = 'flex';
    if (activeUI) activeUI.style.display = 'none';
    if (endBtn) endBtn.style.display = 'none';
    if (muteBtn) muteBtn.style.display = 'none';
    if (modal) modal.style.display = 'flex';
    
    const p = ringtone?.play();
    if (p && typeof p.catch === 'function') {
        p.catch(() => console.debug('Ringtone autoplay blocked'));
    }

    const acceptBtn = document.getElementById('acceptCallBtn');
    const rejectBtn = document.getElementById('rejectCallBtn');

    if (acceptBtn) {
        acceptBtn.onclick = async () => {
            try { if (ringtone) ringtone.pause(); } catch (e) {}
            
            const pending = pendingOffers[fromPubId];
            if (!pending || !pending.offer) {
                console.warn('No pending offer for', fromPubId);
                const inUI = getIncomingCallUI();
                const acUI = getActiveCallUI();
                const eBtn = getEndCallBtn();
                const mBtn = getMuteCallBtn();
                if (inUI) inUI.style.display = 'none';
                if (acUI) acUI.style.display = 'flex';
                if (eBtn) eBtn.style.display = 'inline-block';
                if (mBtn) mBtn.style.display = 'inline-block';
                return;
            }

            const inUI = getIncomingCallUI();
            const acUI = getActiveCallUI();
            const eBtn = getEndCallBtn();
            const mBtn = getMuteCallBtn();
            if (inUI) inUI.style.display = 'none';
            if (acUI) acUI.style.display = 'flex';
            if (eBtn) eBtn.style.display = 'inline-block';
            if (mBtn) mBtn.style.display = 'inline-block';

            await initLocalAudio();

            let pc = peerConnections[fromPubId];
            if (!pc) {
                pc = createPeerConnection(fromPubId, pending.conversation_id);
                peerConnections[fromPubId] = pc;
            }

            try {
                await pc.setRemoteDescription(new RTCSessionDescription(pending.offer));
            } catch (err) {
                console.error('setRemoteDescription failed:', err);
            }

            if (pendingIceCandidates[fromPubId]) {
                for (const ice of pendingIceCandidates[fromPubId]) {
                    try { await pc.addIceCandidate(new RTCIceCandidate(ice)); } catch(e){}
                }
                delete pendingIceCandidates[fromPubId];
            }

            try {
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                if (socket) socket.emit('call_signal', {
                    conversation_id: pending.conversation_id,
                    to_public_id: fromPubId,
                    signal_type: 'answer',
                    signal_data: answer
                });
            } catch (err) {
                console.error('Failed to create/send answer:', err);
            }

            delete pendingOffers[fromPubId];
        };
    }

    if (rejectBtn) {
        rejectBtn.onclick = () => {
            try { if (ringtone) ringtone.pause(); } catch (e) {}
            if (socket) socket.emit('call_end', { conversation_id: conversationId, target_public_id: fromPubId });
            const m = getCallModal();
            if (m) m.style.display = 'none';
            delete pendingOffers[fromPubId];
            currentCallTarget = null;
        };
    }
}

// ===== Outgoing Call UI =====
async function startOutgoingCallUI(targetName, targetPubId, conversationId, avatarUrl = '') {
    const safeName = (typeof targetName === 'string' && targetName.length) ? targetName : 'Unknown';
    const initial = (safeName && safeName.charAt) ? safeName.charAt(0) : '?';

    console.log('🟢 startOutgoingCallUI called with:', { safeName, targetPubId, conversationId });

    currentCallTarget = targetPubId || null;
    
    const callerName = getCallerName();
    const callerAvatar = getCallerAvatar();
    const incomingUI = getIncomingCallUI();
    const activeUI = getActiveCallUI();
    const endBtn = getEndCallBtn();
    const muteBtn = getMuteCallBtn();
    const modal = getCallModal();
    const videoContainer = getCallVideoContainer();

    if (callerName) {
        callerName.innerText = safeName;
        console.log('✅ Set caller name:', safeName);
    } else {
        console.warn('❌ callerName not found');
    }

    if (callerAvatar) {
      callerAvatar.src = avatarUrl ||
        `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect fill='%2364748b' width='80' height='80'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='white' font-size='32'%3E${encodeURIComponent(initial)}%3C/text%3E%3C/svg%3E`;
      console.log('✅ Set caller avatar');
    } else {
        console.warn('❌ callerAvatar not found');
    }

    console.log('Modal elements:', { callModal: !!modal, incomingCallUI: !!incomingUI, activeCallUI: !!activeUI });

    if (incomingUI) incomingUI.style.display = 'none';
    if (activeUI) {
        activeUI.style.display = 'flex';
        activeUI.style.position = 'relative';
        activeUI.style.zIndex = '100000';
        console.log('✅ Showed activeCallUI');
    } else {
        console.warn('❌ activeCallUI not found');
    }
    if (endBtn) endBtn.style.display = 'inline-block';
    if (muteBtn) muteBtn.style.display = 'inline-block';
    if (modal) {
        modal.style.display = 'flex';
        modal.style.position = 'fixed';
        modal.style.top = '0';
        modal.style.left = '0';
        modal.style.width = '100%';
        modal.style.height = '100%';
        modal.style.zIndex = '99999';
        console.log('✅ Showed callModal with inline styles');
    } else {
        console.warn('❌ callModal not found');
    }

    await startCall(targetPubId, conversationId, false);
}

async function startCall(targetPubId, conversationId, isAnswering = false) {
    await initLocalAudio();

    let pc = peerConnections[targetPubId];
    if (!pc) {
        pc = createPeerConnection(targetPubId, conversationId);
        peerConnections[targetPubId] = pc;
    }

    if (!isAnswering) {
        try {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            if (socket) socket.emit('call_signal', {
                conversation_id: conversationId,
                to_public_id: targetPubId,
                signal_type: 'offer',
                signal_data: offer
            });
        } catch (err) {
            console.error('Failed to create/send offer:', err);
        }
    }
}

function endCall(targetPubId, conversationId) {
    const pc = peerConnections[targetPubId];
    if (pc) {
        pc.close();
        delete peerConnections[targetPubId];
    }

    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
    }

    // Stop ringtone if playing
    try { if (ringtone) ringtone.pause(); } catch (e) {}

    // Hide all call UI elements
    const m = getCallModal();
    const inUI = getIncomingCallUI();
    const acUI = getActiveCallUI();

    if (m) m.style.display = 'none';
    if (inUI) inUI.style.display = 'none';
    if (acUI) acUI.style.display = 'none';

    // Clean up pending offers (for incoming calls that were ended before acceptance)
    if (pendingOffers[targetPubId]) {
        delete pendingOffers[targetPubId];
    }

    // Clean up pending ICE candidates
    if (pendingIceCandidates[targetPubId]) {
        delete pendingIceCandidates[targetPubId];
    }

    currentCallTarget = null;

    // Emit call_end signal (but only if we haven't already received one)
    if (socket) socket.emit('call_end', { conversation_id: conversationId, target_public_id: targetPubId });
}

// ===== Socket.IO Signaling =====
if (socket) {
  socket.on('call_signal', async (data) => {
      const { conversation_id, from_public_id, signal_type, signal_data, from_name, avatar_url } = data;

      if (signal_type === 'offer') {
          pendingOffers[from_public_id] = { offer: signal_data, conversation_id, from_name, avatar_url };
          showIncomingCall(from_name, from_public_id, conversation_id, avatar_url);
          return;
      }

      if (signal_type === 'answer') {
          const pc = peerConnections[from_public_id];
          if (!pc) {
              console.warn('Received answer but no local pc exists for', from_public_id);
              return;
          }
          try {
              await pc.setRemoteDescription(new RTCSessionDescription(signal_data));
          } catch (err) { console.error('setRemoteDescription (answer) failed:', err); }

          if (pendingIceCandidates[from_public_id]) {
              for (const ice of pendingIceCandidates[from_public_id]) {
                  try { await pc.addIceCandidate(new RTCIceCandidate(ice)); } catch(e){}
              }
              delete pendingIceCandidates[from_public_id];
          }
          return;
      }

      if (signal_type === 'ice') {
          if (!signal_data || !signal_data.candidate) {
              console.log('Received empty ICE candidate (ignored)');
              return;
          }

          const pc = peerConnections[from_public_id];
          if (!pc) {
              pendingIceCandidates[from_public_id] = pendingIceCandidates[from_public_id] || [];
              pendingIceCandidates[from_public_id].push(signal_data);
              return;
          }

          if (!pc.remoteDescription || !pc.remoteDescription.type) {
              pendingIceCandidates[from_public_id] = pendingIceCandidates[from_public_id] || [];
              pendingIceCandidates[from_public_id].push(signal_data);
              return;
          }

          try {
              await pc.addIceCandidate(new RTCIceCandidate(signal_data));
          } catch (err) {
              pendingIceCandidates[from_public_id] = pendingIceCandidates[from_public_id] || [];
              pendingIceCandidates[from_public_id].push(signal_data);
          }
      }
  });

  socket.on('call_end', (data) => {
      const { from_public_id, conversation_id } = data;
      // Always call endCall to clean up UI, regardless of peer connection state
      endCall(from_public_id, conversation_id);
      if (pendingOffers[from_public_id]) delete pendingOffers[from_public_id];
  });

  socket.on('call_failed', (data) => {
      const { reason, target_name } = data;
      if (reason === 'user_offline') {
          alert(`${target_name} is currently offline. They will receive a notification about your call.`);
          // Clean up the call UI since the call couldn't be established
          endCall(currentCallTarget, data.conversation_id);
      }
  });
}

// ===== Initialize on DOM Ready =====
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupCallButtonLogic);
} else {
    setupCallButtonLogic();
}

console.log('call.js loaded');