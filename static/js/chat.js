document.addEventListener('DOMContentLoaded', () => {

  /* Element refs */
  const currentUserId = String(document.getElementById('current-user-id').value);
  const currentUserRole = document.getElementById('current-user-role').value;

  const convoSearch = document.getElementById('convoSearch');
  const conversationListEl = document.getElementById('conversationList');
  const newDMBtn = document.getElementById('newDMBtn');
  const dmComposerWrapper = document.getElementById('dmComposerWrapper');
  const dmCancel = document.getElementById('dm_cancel');
  const dmClassSelect = document.getElementById('dmClassSelect');
  const dmUserList = document.getElementById('dmUserList');
  const refreshBtn = document.getElementById('refreshConvos');
  const newGroupBtn = document.getElementById('newGroupBtn');
  const groupSettingsModal = document.getElementById('groupSettingsModal');
  const groupSettingsClose = document.getElementById('groupSettingsClose');
  const groupRenameBtn = document.getElementById('groupRenameBtn'); // Save button
  const groupNameInput = document.getElementById('groupNameInput');
  const groupMemberList = document.getElementById('groupMemberList');

  const messagesEl = document.getElementById('messages');
  const rightTitle = document.getElementById('rightTitle');
  const rightSub = document.getElementById('rightSub');
  const rightAvatar = document.getElementById('rightAvatar');
  // NEW refs required for the group menu/header
  const rightActions = document.getElementById('rightActions');

  // General menu refs
  const generalMenuWrapper = document.getElementById('generalMenuWrapper');
  const menuBtn = document.getElementById('menuBtn');
  const menuDropdown = document.getElementById('menuDropdown');

  const messageInput = document.getElementById('messageInput');
  function autoResizeTextarea(el){
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }
  messageInput?.addEventListener('input', () => {
    autoResizeTextarea(messageInput);
  });
  const sendDirectBtn = document.getElementById('sendDirect');
  // Group menu logic
  const groupMenuWrapper = document.getElementById('groupMenuWrapper');
  const groupMenuBtn = document.getElementById('groupMenuBtn');
  const groupMenuDropdown = document.getElementById('groupMenuDropdown');

  const backToConversations = document.getElementById('backToConversations');
  if (backToConversations) {
    backToConversations.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        // Reload to check for new messages
        window.location.reload();
      }
    });
  }

  // ============================================
// ADD THIS FUNCTION TO chat.js
// Call it from within openConversation() after the conv is opened
// ============================================

function syncHiddenInputsForCall(conv) {
  if (!conv) return;

  const convIdInput = document.getElementById('current-conversation-id');
  const convTypeInput = document.getElementById('current-conversation-type');
  const convTargetInput = document.getElementById('current-conversation-target');

  if (!convIdInput || !convTypeInput || !convTargetInput) {
    console.warn('Hidden call inputs not found');
    return;
  }

  // Set conversation ID
  convIdInput.value = conv.id || '';

  // Set conversation type (direct or group)
  const convType = conv.type === 'group' ? 'group' : 'direct';
  convTypeInput.value = convType;

  // For DMs, set the target public ID (the other person)
  let targetPubId = '';
  if (convType === 'direct') {
    const other = (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId);
    targetPubId = other ? other.user_public_id : '';
  }
  convTargetInput.value = targetPubId;

  // Dispatch change events so call.js listeners are triggered
  [convIdInput, convTypeInput, convTargetInput].forEach(input => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });

  console.log('✅ Hidden inputs synced for call.js:', { convId: conv.id, convType, targetPubId });
}

// ============================================
// NOW FIND THIS IN openConversation() AND ADD THE CALL:
// ============================================
// Search for this line in openConversation():
//   "messagesEl.lastElementChild?.scrollIntoView({ behavior:'smooth', block:'end' });"
//
// RIGHT AFTER THAT LINE, ADD:
//   syncHiddenInputsForCall(conv);
//
// FULL CONTEXT (around line 580-590 in your original chat.js):
// ============================================

  async function openConversation(convId){
  currentConversationId = convId;
  pendingReceiverId = pendingReceiverLabel = null;
  generalMenuWrapper.style.display = 'block';
  if (dmComposerWrapper) dmComposerWrapper.style.display = 'none';

  const conv = conversationsCache.find(c => c.id === convId) || {};
  isGroupChat = conv.type === 'group';

  const other = (conv.type === 'direct')
    ? (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId) || {}
    : (conv.participants || [])[0] || {};

  try {
    const res = await fetch(`/chat/conversations/${convId}/messages`);
    if (!res.ok) {
      messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Could not open conversation</div>`;
      return;
    }
    const msgs = await res.json();
    if (!Array.isArray(msgs)) {
      messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Unexpected response</div>`;
      return;
    }

    messagesEl.innerHTML = '';

    // ... [rest of message rendering code] ...

    messagesEl.lastElementChild?.scrollIntoView({ behavior:'smooth', block:'end' });

    const opened = conversationsCache.find(c => c.id === convId);
    if (opened) opened.unread_count = 0;
    await markConversationAsRead(convId);
    syncHiddenInputsForCall(conv);
    await loadConversations();
  } catch (err) {
    console.error('openConversation', err);
    messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Network error</div>`;
  }
}

async function markConversationRead(conversationId) {
    try {
        await fetch('/chat/mark_read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content
            },
            body: JSON.stringify({
                conversation_id: conversationId
            })
        });
    } catch (e) {
        console.warn('Failed to mark conversation read');
    }
}

  /* ============================
   Load DM classes from backend
   ============================ */
  async function loadDMClasses() {
    if (!dmClassSelect) return;
    dmClassSelect.innerHTML = '<option value="">Loading classes…</option>';

    try {
      const res = await fetch('/chat/classes');
      const data = await res.json();

      if (!Array.isArray(data) || data.length === 0) {
        dmClassSelect.innerHTML = '<option value="">No classes available</option>';
        return;
      }

      dmClassSelect.innerHTML = '<option value="">Select a class</option>';
      data.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name;
        dmClassSelect.appendChild(opt);
      });
    } catch (err) {
      console.error('loadDMClasses', err);
      dmClassSelect.innerHTML = '<option value="">Error loading classes</option>';
    }
  }

  async function loadDMUsers({ role, class_id } = {}) {
  if (!dmUserList) return;
  dmUserList.innerHTML = 'Loading users…';

  try {
    let url = `/chat/users?role=${role}`;
    if (class_id) url += `&class_id=${class_id}`;

    const res = await fetch(url);
    const users = await res.json();

    if (!Array.isArray(users) || users.length === 0) {
      dmUserList.innerHTML = 'No users found';
      return;
    }

    dmUserList.innerHTML = '';
    users.forEach(u => {
      const btn = document.createElement('button');
      btn.textContent = u.name;
      btn.className = 'dm-user-btn';
      btn.addEventListener('click', () => openDM(u.id, u.name));
      dmUserList.appendChild(btn);
    });

  } catch (err) {
    console.error('loadDMUsers', err);
    dmUserList.innerHTML = 'Error loading users';
  }
}

  //groupMenuBtn?.addEventListener('click', e => {
  //  e.stopPropagation();
  //  const isVisible = groupMenuDropdown.style.display === 'block';
  //  groupMenuDropdown.style.display = isVisible ? 'none' : 'block';
  //});

  // Toggle general menu (3-dot)
  menuBtn?.addEventListener('click', e => {
    e.stopPropagation();
    if (!menuDropdown) return;
    const isVisible = menuDropdown.style.display === 'block';
    menuDropdown.style.display = isVisible ? 'none' : 'block';
    menuBtn.setAttribute('aria-expanded', (!isVisible).toString());
  });

  // Hide both dropdowns when clicking outside — safe checks
  document.addEventListener('click', () => {
    if (groupMenuDropdown) groupMenuDropdown.style.display = 'none';
    if (menuDropdown) {
      menuDropdown.style.display = 'none';
      menuBtn?.setAttribute('aria-expanded', 'false');
    }
  });

    // menu actions (safe)
    messagesEl.addEventListener('click', e => {
      const replyBox = e.target.closest('.reply-link');
      if (!replyBox) return;

      const targetId = replyBox.dataset.replyId;
      if (!targetId) return;

      const targetMsg = messagesEl.querySelector(
        `.msg[data-msg-id="${targetId}"]`
      );

      if (!targetMsg) return;

      targetMsg.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // 🔦 highlight effect
      targetMsg.classList.add('reply-highlight');
      setTimeout(() => targetMsg.classList.remove('reply-highlight'), 1200);
    });

    menuDropdown?.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      if (action === 'search') {
        convoSearch?.focus();
      } else if (action === 'mute') {
        alert('Mute notifications - feature not implemented yet');
      } else if (action === 'clear_chat') {
        if (!currentConversationId) return alert('No open conversation to clear.');
        if (confirm('Are you sure you want to clear this chat?')) {
          const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
          try {
            await fetch(`/chat/conversations/${encodeURIComponent(currentConversationId)}/clear`, {
              method: 'POST',
              headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' }
            });
            // reload messages
            await openConversation(currentConversationId);
          } catch (err) {
            console.error('clear chat', err);
            alert('Error clearing chat');
          }
        }
      }
      // hide dropdown afterwards
      if (menuDropdown) menuDropdown.style.display = 'none';
      menuBtn?.setAttribute('aria-expanded', 'false');
    });
  });

  // 3-dot menu actions
  menuDropdown.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      if(action === 'search') {
        convoSearch?.focus();
      } else if(action === 'add_members') {
        // Open add participants modal for the current group
        groupSettingsModal.dataset.mode = 'add_members';
        groupSettingsModal.style.display = 'flex';
        groupNameInput.style.display = 'none';
        document.querySelector('#groupSettingsModal h5').textContent = 'Add Members';
        groupRenameBtn.textContent = 'Add Members';

        // Load users not in the group
        groupMemberList.innerHTML = 'Loading users…';
        const conv = conversationsCache.find(c => c.id === currentConversationId);
        const currentMembers = new Set((conv.participants || []).map(p => p.user_public_id));

        try {
          const roles = ['student', 'teacher', 'parent', 'admin'];
          const users = [];
          for (const role of roles) {
            const res = await fetch(`/chat/users?role=${role}`);
            const data = await res.json();
            data.forEach(u => {
              if (!currentMembers.has(String(u.id))) {
                users.push({ ...u, role });
              }
            });
          }

          groupMemberList.innerHTML = '';
          if (users.length === 0) {
            groupMemberList.innerHTML = 'No additional users available';
            return;
          }

          users.forEach(u => {
            const item = document.createElement('div');
            item.style.display = 'flex';
            item.style.alignItems = 'center';
            item.style.gap = '6px';

            item.innerHTML = `
              <input type="checkbox" value="${u.id}" id="user-${u.id}">
              <label for="user-${u.id}">${u.name} (${u.role})</label>
            `;

            const checkbox = item.querySelector('input');
            checkbox.addEventListener('change', e => {
              if (e.target.checked) {
                groupMembers.push(u.id);
              } else {
                groupMembers = groupMembers.filter(id => id !== u.id);
              }
            });

            groupMemberList.appendChild(item);
          });
        } catch (err) {
          console.error(err);
          groupMemberList.innerHTML = 'Error loading users';
        }
      } else if(action === 'mute') {
        alert('Mute notifications - feature not implemented yet');
      } else if(action === 'clear_chat') {
        if(confirm('Are you sure you want to clear this chat?')) {
          const csrf = document.querySelector('meta[name="csrf-token"]').content;
          try {
            await fetch(`/chat/conversations/${currentConversationId}/clear`, {
              method: 'POST',
              headers: { 'X-CSRFToken': csrf }
            });
            openConversation(currentConversationId);
          } catch(err) {
            alert('Error clearing chat');
          }
        }
      }
      menuDropdown.style.display = 'none';
    });
  });

  // Show menu only for groups
  function toggleGroupMenu(conv) {
      const isGroup = conv?.type === 'group';
      if (groupMenuWrapper) groupMenuWrapper.style.display = isGroup ? 'flex' : 'none';
      if (rightActions) rightActions.style.display = isGroup ? 'flex' : 'none';
  }

  /* Local state */
  let currentConversationId = null;
  let pendingReceiverId = null;
  let pendingReceiverLabel = null;
  let conversationsCache = [];
  let participantNameMap = {};
  let typingTimeout = null;
  let replyToMessage = null;
  let isGroupChat = false;
  let selectedDMRole = null;

/* ============================
   DM STEP VISIBILITY CONTROLLER
   ============================ */
function showDMStep(stepId) {
  const steps = ['dmStepRole', 'dmStepClass', 'dmStepUsers'];
  steps.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = (id === stepId) ? 'block' : 'none';
  });
}

document.querySelectorAll('.dm-role-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    selectedDMRole = btn.dataset.role;
    dmUserList.innerHTML = '';

    // Teachers go straight to users
    if (selectedDMRole === 'teacher') {
      showDMStep('dmStepUsers');
      loadDMUsers({ role: selectedDMRole });
    } else {
      showDMStep('dmStepClass');
      loadDMClasses(); // <-- FETCH CLASSES HERE
    }
  });
});

document.getElementById('dmClassSelect')?.addEventListener('change', function () {
  if (!this.value || !selectedDMRole) return;

  showDMStep('dmStepUsers');
  loadDMUsers({
    role: selectedDMRole,
    class_id: this.value
  });
});

document.getElementById('conversationList')?.addEventListener('click', async (e) => {
    const convItem = e.target.closest('.conv-item');
    if (!convItem) return;

    const convId = convItem.dataset.conversationId;

    // ✅ MARK AS READ
    markConversationRead(convId);

    // optional: fetch messages for context (but don't auto-trigger call UI)
    // try {
    //     const res = await fetch(`/chat/conversations/${convId}/messages`);
    //     const messages = await res.json();
    //     syncCallContextFromConversation(convItem, messages);
    // } catch (e) {}
});

// ============================================
// REPLACE THIS ENTIRE BLOCK IN chat.js:
// ============================================

// Call button event listener is now handled in call.js
// document.getElementById('startCallBtn')?.addEventListener('click', async function() {
//     const convId = document.getElementById('current-conversation-id').value;
//     const targetPubId = document.getElementById('current-conversation-target').value;
//     const convType = document.getElementById('current-conversation-type').value;

//     if (!convId) {
//         return alert("Select a conversation first");
//     }

//     if (convType === 'group') {
//         return alert('Group calls are not supported yet');
//     }

//     if (!targetPubId) {
//         return alert('Cannot initiate call - target user not found');
//     }

//     // Get the target name from the active conversation
//     const activeConv = document.querySelector('.conv-item.active');
//     const targetName = activeConv?.querySelector('.conv-title')?.innerText || 'Unknown';

//     console.log('📞 Starting call to:', { targetName, targetPubId, convId });

//     // Call the function from call.js (which is already loaded)
//     if (typeof startOutgoingCallUI === 'function') {
//         await startOutgoingCallUI(targetName, targetPubId, convId);
//     } else {
//         alert('Call system not ready. Please refresh the page.');
//         console.error('startOutgoingCallUI function not found. Is call.js loaded?');
//     }
// });

const msgMenu = document.getElementById('msgContextMenu');

// Right-click handler
document.getElementById('messages').addEventListener('contextmenu', function(e){
    const msgEl = e.target.closest('.msg-item'); // <- your message element class
    if(msgEl){
        e.preventDefault();
        msgMenu.style.top = e.pageY + 'px';
        msgMenu.style.left = e.pageX + 'px';
        msgMenu.style.display = 'block';

        // store the message id on menu for actions
        msgMenu.dataset.msgId = msgEl.dataset.msgId;
    }
});

// Hide menu on click elsewhere
document.addEventListener('click', function(){
    msgMenu.style.display = 'none';
});

  /* Utilities */
  const safeText = s => String(s || '');
  const fmtTime = iso => iso ? new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '';
  const fmtDate = iso => {
    if(!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString([], {month:'short', day:'numeric', year: d.getFullYear()===new Date().getFullYear() ? undefined : 'numeric'});
  };
  const initialsFromName = name => {
    if(!name) return 'U';
    return name.trim().split(/\s+/).map(n => n[0]||'').join('').slice(0,2).toUpperCase();
  };

  function getUserColor(userId) {
    // Generate a consistent color based on user ID
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#84cc16', '#f97316'];
    let hash = 0;
    for (let i = 0; i < userId.length; i++) {
      hash = userId.charCodeAt(i) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
  }

  function setReplyTo(msg) {
    replyToMessage = msg;
    updateReplyUI();
  }

  function updateReplyUI() {
    const replyDiv = document.getElementById('replyDiv');
    if (replyToMessage) {
      const replyColor = getUserColor(replyToMessage.sender_public_id || replyToMessage.sender_id || '');
      replyDiv.innerHTML = `<div class="reply-quote" style="border-left-color: ${replyColor};">
        <div class="reply-sender" style="color: ${replyColor};">${replyToMessage.sender_name}</div>
        <div class="reply-content">${safeText(replyToMessage.content).slice(0,50)}${replyToMessage.content.length > 50 ? '...' : ''}</div>
      </div><button id="cancelReply" title="Cancel reply">×</button>`;
      replyDiv.style.display = 'flex';
      document.getElementById('cancelReply').addEventListener('click', () => {
        replyToMessage = null;
        updateReplyUI();
      });
    } else {
      replyDiv.style.display = 'none';
    }
  }

  function renderReactions(el, reactions) {
    el.innerHTML = '';
    if (reactions.length === 0) return;

    const grouped = {};
    reactions.forEach(r => {
      if (!grouped[r.emoji]) grouped[r.emoji] = [];
      grouped[r.emoji].push(r);
    });

    Object.keys(grouped).forEach(emoji => {
      const count = grouped[emoji].length;
      const hasMine = grouped[emoji].some(r => r.user_public_id === currentUserId);
      const btn = document.createElement('button');
      btn.className = 'reaction-btn' + (hasMine ? ' mine' : '');
      btn.textContent = `${emoji} ${count}`;
      btn.addEventListener('click', () => toggleReaction(el.dataset.msgId, emoji, hasMine));
      el.appendChild(btn);
    });
  }

  async function toggleReaction(msgId, emoji, hasMine) {
    if (!currentConversationId) return alert('No active conversation');
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    const method = hasMine ? 'DELETE' : 'POST';
    const url = `/chat/conversations/${currentConversationId}/messages/${msgId}/react`;

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ emoji })
      });
      if (!res.ok) throw new Error('Failed to toggle reaction');
    } catch (err) {
      console.error('toggleReaction', err);
      alert('Error toggling reaction');
    }
  }

  function showReactionPicker(el, msg) {
    const picker = document.createElement('div');
    picker.className = 'reaction-picker';
    const emojis = ['👍', '❤️', '😂', '😮', '😢', '😡'];
    emojis.forEach(emoji => {
      const btn = document.createElement('button');
      btn.textContent = emoji;
      btn.addEventListener('click', () => {
        toggleReaction(msg.id, emoji, false);
        picker.remove();
      });
      picker.appendChild(btn);
    });
    el.appendChild(picker);
    setTimeout(() => picker.remove(), 3000); // auto remove
  }

  function fmtLastSeen(iso){
  if (!iso) return 'Last seen a while ago';
  const last = typeof iso === 'string' ? new Date(iso) : new Date(iso * 1000);
  const now = new Date();
  const diffMs = now - last;
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Last seen just now';
  if (diffMins < 60) return `Last seen ${diffMins} min ago`;

  const isToday = last.toDateString() === now.toDateString();
  const optionsTime = { hour: '2-digit', minute: '2-digit' };
  const optionsDate = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };

  if (isToday) {
      return `Last seen today at ${last.toLocaleTimeString([], optionsTime)}`;
  } else {
      return `Last seen on ${last.toLocaleDateString([], optionsDate)}`;
  }
} // <-- closing brace was missing before


  /* Message context menu */
  const menu = document.getElementById('msgContextMenu');
  let activeMsg = null;

  function attachMsgMenu(el, msg){
    let pressTimer = null;

    // Add reaction button on hover
    const reactBtn = document.createElement('button');
    reactBtn.className = 'react-btn';
    reactBtn.textContent = '+';
    reactBtn.style.display = 'none';
    reactBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      showReactionPicker(el, msg);
    });
    el.appendChild(reactBtn);

    el.addEventListener('mouseenter', () => reactBtn.style.display = 'block');
    el.addEventListener('mouseleave', () => reactBtn.style.display = 'none');

    // Right-click (desktop)
    el.addEventListener('contextmenu', e => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, msg);
    });

    // Long-press (mobile)
    el.addEventListener('touchstart', e => {
      pressTimer = setTimeout(() => {
        const t = e.touches[0];
        showMenu(t.clientX, t.clientY, msg);
      }, 550);
    });

    ['touchend','touchmove','touchcancel']
      .forEach(evt => el.addEventListener(evt, ()=> clearTimeout(pressTimer)));
  }

  function showMenu(x, y, msg){
    activeMsg = msg;

    // hide edit/delete if not mine
    menu.querySelector('[data-action="edit"]').style.display =
    menu.querySelector('[data-action="delete"]').style.display =
      (String(msg.sender_public_id) === currentUserId) ? 'block' : 'none';

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.style.display = 'block';
  }

  document.addEventListener('click', () => {
    menu.style.display = 'none';
  });

  const modal = document.getElementById('msgActionModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalInput = document.getElementById('modalInput');
  const modalConfirmText = document.getElementById('modalConfirmText');
  const modalCancel = document.getElementById('modalCancel');
  const modalConfirm = document.getElementById('modalConfirm');

  let modalAction = null; // "edit", "forward", "delete"
  let modalMsg = null;
  modalConfirm.disabled = false;

  menu.addEventListener('click', e => {
    const action = e.target.dataset.action;
    if (!action || !activeMsg) return;
    modalMsg = activeMsg;

    modalAction = action;

    if (action === 'reply') {
      setReplyTo(activeMsg);
      menu.style.display = 'none';
      return;
    }

    if (action === 'copy') {
      navigator.clipboard.writeText(activeMsg.content || '');
      menu.style.display = 'none';
      return;
    }

    // Prepare modal
    modalInput.style.display = (action === 'edit' || action === 'forward') ? 'block' : 'none';
    modalConfirmText.style.display = (action === 'delete') ? 'block' : 'none';

    modalTitle.textContent =
      action === 'edit' ? 'Edit Message' :
      action === 'forward' ? 'Forward Message' :
      'Delete Message';

    if (action === 'forward') {
      modalInput.style.display = 'none';
      modalConfirmText.style.display = 'none';

      const convoListEl = document.getElementById('modalConvoList');
      convoListEl.innerHTML = '';
      convoListEl.style.display = 'block';

      modal.dataset.targetConvoId = '';
      modalConfirm.disabled = true; // 🔒 disabled until selection

      const forwardList = conversationsCache.filter(c => c.id !== currentConversationId);

      if (forwardList.length === 0) {
        convoListEl.innerHTML =
          '<div style="padding:8px; color:#555;">No other conversations to forward to.</div>';
        return;
      }

      forwardList.forEach(conv => {
        const item = document.createElement('div');
        item.style.padding = '6px 8px';
        item.style.borderRadius = '6px';
        item.style.cursor = 'pointer';
        item.style.display = 'flex';
        item.style.alignItems = 'center';
        item.style.gap = '6px';

        const other =
          (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId)
          || conv.participants?.[0]
          || {};

        item.innerHTML = `
          <div style="width:28px;height:28px;border-radius:4px;background:#64748b;
                      display:grid;place-items:center;color:#fff;font-size:12px;">
            ${initialsFromName(other.name)}
          </div>
          <div style="flex:1;">
            <div style="font-size:13px;font-weight:500;">${other.name || 'Conversation'}</div>
            <div style="font-size:11px;color:#6b7280;">
              ${conv.last_message ? (conv.last_message.content || '').slice(0,40) : 'No messages yet'}
            </div>
          </div>
        `;

        item.addEventListener('click', () => {
          // clear previous selection
          convoListEl.querySelectorAll('.selected')
            .forEach(el => el.classList.remove('selected'));

          item.classList.add('selected');
          item.style.background = '#dbeafe';

          modal.dataset.targetConvoId = conv.id;
          modalConfirm.disabled = false; // ✅ now enabled
        });

        convoListEl.appendChild(item);
      });
    }

    modal.style.display = 'flex';
    if (action !== 'delete') modalInput.focus();

    menu.style.display = 'none';
  });

  // Modal buttons
  modalCancel.addEventListener('click', () => {
    modal.style.display = 'none';
    modalInput.value = '';
  });

  modalConfirm.addEventListener('click', async () => {
  if (!modalMsg || !modalAction) return;

  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  if (modalAction === 'edit') {
    const newText = modalInput.value.trim();
    if (!newText) return alert('Message cannot be empty');

    await fetch(`/chat/conversations/${currentConversationId}/messages/${modalMsg.id}/edit`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({ content: newText })
    });

    openConversation(currentConversationId);
  }

  if (modalAction === 'forward') {
    const targetId = modal.dataset.targetConvoId;
    if (!targetId) return alert('Select a conversation first');

    await fetch(`/chat/conversations/${currentConversationId}/messages/${modalMsg.id}/forward`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({ target_conversation_id: targetId })
    });

    alert('Message forwarded');
  }

  if (modalAction === 'delete') {
    await fetch(`/chat/conversations/${currentConversationId}/messages/${modalMsg.id}/delete`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf }
    });

    openConversation(currentConversationId);
  }

  modal.style.display = 'none';
  modalInput.value = '';
});

  /* Search debounce */
  let searchTimer = null;
  convoSearch?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderConversations, 180);
  });

  convoSearch?.addEventListener('focus', () => {
    dmComposerWrapper && (dmComposerWrapper.style.display = 'none');
  });

  /* DM composer open/close */
  newDMBtn?.addEventListener('click', () => {
  const isOpen = dmComposerWrapper.style.display === 'block';

  if (isOpen) {
    dmComposerWrapper.style.display = 'none';
    return;
  }

  // reset DM flow
  selectedDMRole = null;
  document.getElementById('dmClassSelect').value = '';
  dmUserList.innerHTML = '';

  dmComposerWrapper.style.display = 'block';
  showDMStep('dmStepRole'); // 🔒 ONLY STEP 1
});

dmCancel?.addEventListener('click', () => {
  dmComposerWrapper.style.display = 'none';
  selectedDMRole = null;
  document.getElementById('dmClassSelect').value = '';
  dmUserList.innerHTML = '';
  showDMStep('dmStepRole');
});

  /* Load & render conversations */
  async function loadConversations(){
    try {
      const res = await fetch('/chat/conversations');
      const data = await res.json();
      conversationsCache = data || [];

      participantNameMap = {};
      conversationsCache.forEach(conv => {
        (conv.participants || []).forEach(p => {
          // key by public id
          participantNameMap[p.user_public_id] = p.name;
        });
      });

      renderConversations();
    } catch (err) {
      console.error('loadConversations', err);
    }
  }

  function convoTitle(conv){
    if (conv.type === 'direct') {
      const other = (conv.participants || [])
        .find(p => String(p.user_public_id) !== currentUserId)
        || {};
      return (other.name || 'Direct Message').toLowerCase();
    }

    // ✅ GROUP
    return (conv.name || 'Group').toLowerCase();
  }

  function renderConversations(){
    if (!conversationListEl) return;
    conversationListEl.innerHTML = '';

    const q = (convoSearch?.value || '').toLowerCase().trim();
    let list = (conversationsCache || []).slice();

    if (q) {
      list = list.filter(c =>
        convoTitle(c).includes(q) ||
        (c.last_message && ((c.last_message.content || '') + ' ' + (c.last_message.sender_role || '')).toLowerCase().includes(q))
      );
    }

    list.sort((a,b) => {
      const ua = (a.unread_count || 0) > 0 ? 1 : 0;
      const ub = (b.unread_count || 0) > 0 ? 1 : 0;
      if (ua !== ub) return ub - ua;
      return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
    });

    if(list.length === 0){
      const empty = document.createElement('div');
      empty.className = 'no-conversations';
      empty.textContent = 'No conversations match your filters.';
      conversationListEl.appendChild(empty);
      return;
    }

    list.forEach(conv => {
      const item = document.createElement('div');
      item.className = 'conv-item' + (conv.id === currentConversationId ? ' active' : '');

      const other = (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId) || (conv.participants || [])[0] || {};
      const avatar = document.createElement('div');
      avatar.className = 'conv-avatar';
      avatar.style.background = ({ admin:'#8b5cf6', teacher:'#10b981', student:'#3b82f6', parent:'#fb923c' }[other.role] || '#64748b');
      if (conv.type === 'group') {
        avatar.textContent = conv.participants?.length ? conv.participants.length : '0';
        avatar.style.background = '#0ea5e9';
      } else {
        avatar.textContent = initialsFromName(other.name);
      }
      item.appendChild(avatar);

      const meta = document.createElement('div'); meta.className = 'conv-meta';
      const title = document.createElement('div'); title.className = 'conv-title';
      if (conv.type === 'group') {
      title.textContent = conv.name || 'Unnamed Group'; item.classList.add('group'); } else { title.textContent = other.name || `${other.role} ${other.user_public_id}`;}
      meta.appendChild(title);

      const sub = document.createElement('div'); sub.className = 'conv-sub';
      if (conv.last_message) {
        const lm = conv.last_message;
        const preview = document.createElement('span');
        preview.textContent = `${(lm.sender_role || '').toUpperCase()}: ${String(lm.content || '').slice(0, 52)}`;
        sub.appendChild(preview);
      } else {
        const empty = document.createElement('span');
        empty.className = 'text-muted';
        empty.textContent = 'No messages yet';
        sub.appendChild(empty);
      }
      meta.appendChild(sub);
      item.appendChild(meta);

      const right = document.createElement('div');
      right.className = 'conv-right';
      if (conv.unread_count && conv.unread_count > 0) {
        const u = document.createElement('span');
        u.className = 'badge bg-danger text-white ms-2';
        u.textContent = conv.unread_count;
        right.appendChild(u);
      }
      item.appendChild(right);

      item.dataset.conversationId = conv.id;
      item.addEventListener('click', () => openConversation(conv.id));
      conversationListEl.appendChild(item);
    });
  }

  /* Open DM by clicking available user (from DM composer) */
  function openDM(userId, userLabel){
  const existing = (conversationsCache || []).find(c => c.type === 'direct' && (c.participants || []).some(p => String(p.user_public_id) === String(userId)));
  if (existing){
    openConversation(existing.id);
    pendingReceiverId = pendingReceiverLabel = null;
    dmComposerWrapper.style.display = 'none'; // ← fix here
    // Update header
    rightTitle.textContent = existing.name || 'Group';
    rightSub.textContent = existing.participants.map(p => p.name).join(',');

    toggleGroupMenu(existing);
    return;
  }

  pendingReceiverId = String(userId);
  pendingReceiverLabel = userLabel || (`User ${userId}`);
  currentConversationId = null;
  messagesEl.innerHTML = '';
  generalMenuWrapper.style.display = 'block';
  isGroupChat = false;

  rightTitle.textContent = `DM • ${pendingReceiverLabel}`;
  rightSub.textContent = 'Start the conversation here';
  rightAvatar.textContent = (pendingReceiverLabel || 'DM').slice(0,2).toUpperCase();
  rightAvatar.style.background = '#3b82f6';
  messageInput?.focus();

  dmComposerWrapper.style.display = 'none'; // ← fix here too
}

  /* Open an existing conversation and render messages */
  async function openConversation(convId){
  currentConversationId = convId;
  pendingReceiverId = pendingReceiverLabel = null;
  generalMenuWrapper.style.display = 'block';
  if (dmComposerWrapper) dmComposerWrapper.style.display = 'none';

  const conv = conversationsCache.find(c => c.id === convId) || {};
  isGroupChat = conv.type === 'group';

  // ====== DEFINE `other` HERE ======
  // For direct chats, find the other participant
  const other = (conv.type === 'direct')
    ? (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId) || {}
    : (conv.participants || [])[0] || {}; // For groups, use first participant as fallback
  // =================================

  

  try {
    const res = await fetch(`/chat/conversations/${convId}/messages`);
    if (!res.ok) {
      messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Could not open conversation</div>`;
      return;
    }
    const msgs = await res.json();
    if (!Array.isArray(msgs)) {
      messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Unexpected response</div>`;
      return;
    }

    messagesEl.innerHTML = '';

    // group by day
    const byDay = {};
    msgs.forEach(m => {
      const key = new Date(m.created_at || m.timestamp || Date.now()).toDateString();
      if (!byDay[key]) byDay[key] = [];
      byDay[key].push(m);
    });

    Object.keys(byDay).sort((a,b) => new Date(a) - new Date(b)).forEach(day => {
      const dayMsgs = byDay[day];
      const sep = document.createElement('div'); sep.className = 'date-sep';
      sep.textContent = fmtDate(dayMsgs[0].created_at || dayMsgs[0].timestamp || day);
      messagesEl.appendChild(sep);

      let lastSender = null;
      let groupEl = null;
      dayMsgs.forEach(m => {
        const sender = String(m.sender_public_id || '');
        const isMine = sender === currentUserId;
        if (sender !== lastSender) {
          groupEl = document.createElement('div'); groupEl.className = 'msg-group';
          lastSender = sender;
        }

        const mEl = document.createElement('div');
        mEl.className = 'msg ' + (isMine ? 'sent' : 'received');
        mEl.dataset.msgId = m.id;
        mEl.dataset.sender = m.sender_public_id;
        const editedTag = m.edited_at ? ' • edited' : '';

        let replyHtml = '';
        if (m.reply_to) {
          const replyColor = getUserColor(m.reply_to.sender_public_id || m.reply_to.sender_id || '');
          replyHtml = `
            <div class="reply-quote reply-link"
                data-reply-id="${m.reply_to.id}"
                style="border-left-color:${replyColor}">
              <div class="reply-sender" style="color:${replyColor}">
                ${safeText(m.reply_to.sender_name)}
              </div>
              <div class="reply-content">
                ${safeText(m.reply_to.content).slice(0, 80)}
              </div>
            </div>
          `;
        }

        if (isMine) {
          mEl.innerHTML = `
            ${replyHtml}
            <div class="msg-content">${safeText(m.content || m.message || '')}</div>
            <div class="meta">
              ${fmtTime(m.created_at || m.timestamp || '')}${editedTag}
            </div>
            <div class="reactions" data-msg-id="${m.id}"></div>
          `;
        } else {
          mEl.innerHTML = `
            ${isGroupChat ? `<div class="sender-name" style="color: ${getUserColor(m.sender_public_id)}">${m.sender_name || participantNameMap[m.sender_public_id] || 'Unknown'}</div>` : ''}
            ${replyHtml}
            <div class="msg-content">${safeText(m.content || m.message || '')}</div>
            <div class="meta">
              ${fmtTime(m.created_at || m.timestamp || '')}${editedTag}
            </div>
            <div class="reactions" data-msg-id="${m.id}"></div>
          `;
        }

        attachMsgMenu(mEl, m);
        groupEl.appendChild(mEl);

        const reactionsEl = mEl.querySelector('.reactions');
        renderReactions(reactionsEl, m.reactions || []);
        mEl._reactions = m.reactions || [];
        messagesEl.appendChild(groupEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      });
    });

    // ===== UPDATE RIGHT HEADER =====
    if (conv.type === 'group') {
      rightTitle.textContent = conv.name || 'Group Chat';
      rightSub.textContent = `${conv.participants?.length || 0} members`;
      rightAvatar.textContent = conv.participants?.length || '0';
      rightAvatar.style.background = '#0ea5e9';
    } else {
      rightTitle.textContent = other.name || 'Unknown User';
      rightSub.textContent = conv.last_message ? `${(conv.last_message.sender_role || '').toUpperCase()} • ${fmtTime(conv.last_message.created_at || conv.last_message.timestamp || '')}` : 'Conversation';
      rightAvatar.textContent = initialsFromName(other.name || `${other.role} ${other.user_public_id}`);
      rightAvatar.style.background = ({ admin:'#8b5cf6', teacher:'#10b981', student:'#3b82f6', parent:'#fb923c' }[other.role] || '#64748b');
    }
    // =================================

    setTimeout(() => messagesEl.scrollTop = messagesEl.scrollHeight, 100);
    syncHiddenInputsForCall(conv);  // ← ADD THIS
    await loadConversations();

    // Mobile: show messages, hide conversations
    if (window.innerWidth <= 768) {
      document.querySelector('.left-panel').style.display = 'none';
      document.querySelector('.right-panel').style.display = 'flex';
      if (backToConversations) backToConversations.style.display = 'block';
    }
  } catch (err) {
    console.error('openConversation', err);
    messagesEl.innerHTML = `<div class="no-conversations" style="padding:12px;">Network error</div>`;
  }
}


  /* Append message (optimistic + socket updates) */
  function appendMessage(msg, { prepend = false } = {}) {
    // allow append for open conversation only (temporary conv 'temp' allowed)
    if (String(msg.conversation_id) !== String(currentConversationId) && String(msg.conversation_id) !== 'temp') return;
    const isMine = String(msg.sender_public_id || msg.sender_id || '') === currentUserId;
    const groupEl = document.createElement('div'); groupEl.className = 'msg-group';
    const mEl = document.createElement('div'); mEl.className = 'msg ' + (isMine ? 'sent' : 'received');
    if (msg.id) {mEl.dataset.msgId = msg.id;}
    const content = safeText(msg.content || msg.message || '');
    const created = msg.created_at || msg.timestamp || new Date().toISOString();

    // Reply quote
    let replyHtml = '';
    if (msg.reply_to) {
      const replyColor = getUserColor(msg.reply_to.sender_public_id || msg.reply_to.sender_id || '');
      replyHtml = `
        <div class="reply-quote reply-link"
             data-reply-id="${msg.reply_to.id}"
             style="border-left-color:${replyColor}">
          <div class="reply-sender" style="color:${replyColor}">
            ${safeText(msg.reply_to.sender_name)}
          </div>
          <div class="reply-content">
            ${safeText(msg.reply_to.content).slice(0,80)}
          </div>
        </div>
      `;
    }

    if (isMine) {
      mEl.innerHTML = `${replyHtml}<div class="msg-content">${content}</div><div class="meta">${fmtTime(created)}</div><div class="reactions" data-msg-id="${msg.id}"></div>`;
    } else {
      mEl.innerHTML = `${isGroupChat ? `<div class="sender-name" style="color: ${getUserColor(String(msg.sender_public_id || msg.sender_id))}">${msg.sender_name || participantNameMap[String(msg.sender_public_id || msg.sender_id)] || 'Unknown'}</div>` : ''}${replyHtml}<div class="msg-content">${content}</div><div class="meta">${fmtTime(created)}</div><div class="reactions" data-msg-id="${msg.id}"></div>`;
    }

    groupEl.appendChild(mEl);
    // Initialize reactions
    const reactionsEl = mEl.querySelector('.reactions');
    renderReactions(reactionsEl, []);
    mEl._reactions = [];
    messagesEl.lastElementChild?.scrollIntoView({ behavior:'smooth', block:'end' });
  }

  /* Sending messages (HTTP + optimistic UI) */
  messageInput?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendDirectBtn?.click();
    }
  });

  sendDirectBtn?.addEventListener('click', async () => {
    const text = (messageInput?.value || '').trim();
    if (!text) return;

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    // Capture reply info BEFORE doing any resets so it can be sent
    const replyId = replyToMessage ? replyToMessage.id : null;
    const replyObj = replyToMessage ? {
      id: replyToMessage.id,
      sender_public_id: replyToMessage.sender_public_id,
      sender_name: replyToMessage.sender_name,
      content: replyToMessage.content
    } : null;

    // If we are in an open conversation (group or direct), post to conversation endpoint
    if (currentConversationId) {
      // optimistic append — include the reply object so the UI shows the quote immediately
      const tmpMsg = {
        conversation_id: currentConversationId,
        sender_public_id: currentUserId,
        sender_role: currentUserRole,
        sender_name: 'You',
        content: text,
        reply_to: replyObj,              // <<-- include reply in optimistic UI
        created_at: new Date().toISOString()
      };
      appendMessage(tmpMsg);

      // clear the input, but DO NOT clear replyToMessage yet (we need it for the request)
      messageInput.value = '';

      try {
        const res = await fetch(`/chat/conversations/${encodeURIComponent(currentConversationId)}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
          body: JSON.stringify({
            message: text,
            reply_to_message_id: replyId       // <<-- use replyId captured earlier
          })
        });

        if (!res.ok) {
          const txt = await res.text();
          console.warn('Send to conversation failed:', res.status, txt);
          alert(`Send failed (${res.status})`);
          return;
        }

        const data = await res.json();
        if (!data.success) {
          console.warn('send failed', data);
          alert(data.error || 'Send failed');
          return;
        }

        // **Only after success** clear reply state and update UI
        replyToMessage = null;
        updateReplyUI();

        // refresh UI with authoritative data
        currentConversationId = data.conversation_id || currentConversationId;
        pendingReceiverId = pendingReceiverLabel = null;
        if (currentConversationId) await openConversation(currentConversationId);
        else await loadConversations();
      } catch (err) {
        console.error('sendConversation', err);
        // keep replyToMessage intact to allow retry; user still sees optimistic message
        alert('Network error');
      }

      return;
    }

    // Otherwise no open conversation: fall back to DM creation endpoint

    // derive receiver
    let receiver_public_id = pendingReceiverId || null;
    if (!receiver_public_id && currentConversationId) {
      const conv = (conversationsCache || []).find(c => String(c.id) === String(currentConversationId));
      if (conv) {
        const other = (conv.participants || []).find(p => String(p.user_public_id) !== currentUserId);
        receiver_public_id = other ? other.user_public_id : null;
      }
    }
    if (String(receiver_public_id) === currentUserId) {
      alert('You cannot message yourself.');
      return;
    }

    // optimistic append for DM (include reply)
    const tmpMsg2 = {
      conversation_id: currentConversationId || 'temp',
      sender_public_id: currentUserId,
      sender_role: currentUserRole,
      sender_name: 'You',
      content: text,
      reply_to: replyObj,                  // <<-- include reply in optimistic UI
      created_at: new Date().toISOString()
    };
    appendMessage(tmpMsg2);

    // clear input but DO NOT clear replyToMessage yet
    messageInput.value = '';

    try {
      const res = await fetch('/chat/send_dm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          message: text,
          receiver_public_id: String(receiver_public_id),
          reply_to_message_id: replyId       // <<-- send the captured reply id
        })
      });

      if (!res.ok) {
        const txt = await res.text();
        console.warn('Send failed:', res.status, txt);
        alert(`Send failed (${res.status})`);
        return;
      }

      const data = await res.json();
      if (!data.success) {
        console.warn('send failed', data);
        alert(data.error || 'Send failed');
        return;
      }

      // **Only after success** clear reply state and update UI
      replyToMessage = null;
      updateReplyUI();

      currentConversationId = data.conversation_id || currentConversationId;
      pendingReceiverId = pendingReceiverLabel = null;

      if (currentConversationId) await openConversation(currentConversationId);
      else await loadConversations();

    } catch (err) {
      console.error('sendDirect', err);
      // keep replyToMessage intact so user can retry
      alert('Network error');
    }
  });

  newGroupBtn?.addEventListener('click', async () => {
    groupSettingsModal.style.display = 'flex';
    groupNameInput.value = '';
    groupMemberList.innerHTML = 'Loading users…';
    groupMembers = [];

    try {
      const roles = ['student', 'teacher', 'parent', 'admin'];
      const users = []; // ✅ single declaration

      for (const role of roles) {
        const res = await fetch(`/chat/users?role=${role}`);
        const data = await res.json();
        data.forEach(u => users.push({ ...u, role }));
      }

      groupMemberList.innerHTML = '';

      if (users.length === 0) {
        groupMemberList.innerHTML = 'No users available';
        return;
      }

      users.forEach(u => {
        if (String(u.id) === String(currentUserId)) return;

        const item = document.createElement('div');
        item.style.display = 'flex';
        item.style.alignItems = 'center';
        item.style.gap = '6px';

        item.innerHTML = `
          <input type="checkbox" value="${u.id}" id="user-${u.id}">
          <label for="user-${u.id}">${u.name} (${u.role})</label>
        `;

        const checkbox = item.querySelector('input');
        checkbox.addEventListener('change', e => {
          if (e.target.checked) {
            groupMembers.push(u.id);
          } else {
            groupMembers = groupMembers.filter(id => id !== u.id);
          }
        });

        groupMemberList.appendChild(item);
      });

    } catch (err) {
      console.error(err);
      groupMemberList.innerHTML = 'Error loading users';
    }
  });

  // CLOSE MODAL
  groupSettingsClose?.addEventListener('click', () => {
    groupSettingsModal.style.display = 'none';
    groupNameInput.value = '';
    groupNameInput.style.display = 'block';
    document.querySelector('#groupSettingsModal h5').textContent = 'Group Settings';
    groupRenameBtn.textContent = 'Save';
    groupMembers = [];
    delete groupSettingsModal.dataset.mode;
  });

  // CREATE GROUP or ADD MEMBERS
  groupRenameBtn?.addEventListener('click', async () => {
    const mode = groupSettingsModal.dataset.mode || 'create';
    const csrf = document.querySelector('meta[name="csrf-token"]').content;

    if (mode === 'create') {
      const groupName = groupNameInput.value.trim();
      if (!groupName) return alert('Group name cannot be empty');
      if (groupMembers.length === 0) return alert('Select at least one member');

      try {
        const res = await fetch('/chat/conversations/group/create', {
          method: 'POST',
          headers: { 'Content-Type':'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({
            name: groupName,
            members: groupMembers
          })
        });

        if (!res.ok) throw new Error('Failed to create group');

        const newGroup = await res.json();
        await loadConversations();
        openConversation(newGroup.id);
      } catch (err) {
        console.error(err);
        alert('Error creating group');
      }
    } else if (mode === 'add_members') {
      if (groupMembers.length === 0) return alert('Select at least one member to add');

      try {
        const res = await fetch(`/chat/conversations/${currentConversationId}/add_members`, {
          method: 'POST',
          headers: { 'Content-Type':'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({
            members: groupMembers
          })
        });

        if (!res.ok) throw new Error('Failed to add members');

        const data = await res.json();
        alert(`Added ${data.added.length} members`);
        await loadConversations();
        openConversation(currentConversationId);
      } catch (err) {
        console.error(err);
        alert('Error adding members');
      }
    }

    // Close modal
    groupSettingsModal.style.display = 'none';
    groupNameInput.value = '';
    groupNameInput.style.display = 'block';
    document.querySelector('#groupSettingsModal h5').textContent = 'Group Settings';
    groupRenameBtn.textContent = 'Save';
    groupMembers = [];
    delete groupSettingsModal.dataset.mode;
  });

  /* Socket.IO realtime */
  const socket = (typeof io === 'function') ? io() : null;
  if (socket) {
    socket.on('connect', () => {
      // server uses session to join; emitting helps for debugging
      socket.emit('join', { user_id: currentUserId });
    });
    socket.on('typing', payload => {
      if (String(payload.conversation_id) === String(currentConversationId)) showTypingIndicator(payload.user_role);
    });
    socket.on('presence_update', payload => {
      const { user_public_id, status, last_seen } = payload;

      const conv = conversationsCache.find(c =>
        (c.participants || []).some(p => String(p.user_public_id) === String(user_public_id))
      );

      if (!conv || conv.id !== currentConversationId) return;

      if (status === 'online') {
        rightSub.innerHTML =
          `<span class="presence-dot presence-online"></span>Online`;
      } else {
        rightSub.innerHTML =
          `<span class="presence-dot presence-offline"></span>${fmtLastSeen(last_seen)}`;
      }
    });

    socket.on('new_message', payload => {
      try {
        if (String(payload.conversation_id) === String(currentConversationId)) {
          appendMessage(payload.message);
        }
        loadConversations();
      } catch (e) { console.error('socket new_message', e); }
    });
    socket.on('message_edited', payload => {
      const { conversation_id, message } = payload;

      if (String(conversation_id) !== String(currentConversationId)) return;

      const msgEl = document.querySelector(`[data-msg-id="${message.id}"]`);
      if (!msgEl) return;

      msgEl.querySelector('.msg-content').textContent = message.content;

      const metaEl = msgEl.querySelector('.meta');
      metaEl.textContent =
        `${fmtTime(message.created_at)} • edited`;
    });
    socket.on('reaction_added', payload => {
      const { message_id, reaction } = payload;
      const msgEl = document.querySelector(`[data-msg-id="${message_id}"]`);
      if (!msgEl) return;
      const reactionsEl = msgEl.querySelector('.reactions');
      const existing = msgEl._reactions || [];
      existing.push(reaction);
      msgEl._reactions = existing;
      renderReactions(reactionsEl, existing);
    });
    socket.on('reaction_removed', payload => {
      const { message_id, user_public_id, emoji } = payload;
      const msgEl = document.querySelector(`[data-msg-id="${message_id}"]`);
      if (!msgEl) return;
      const reactionsEl = msgEl.querySelector('.reactions');
      const existing = msgEl._reactions || [];
      const filtered = existing.filter(r => !(r.user_public_id === user_public_id && r.emoji === emoji));
      msgEl._reactions = filtered;
      renderReactions(reactionsEl, filtered);
    });
  }

  function showTypingIndicator(user_role) {
    clearTimeout(typingTimeout);
    const el = document.createElement('div'); el.className = 'typing'; el.id = 'typingIndicator';
    el.innerHTML = `<span class="dot"></span><span class="dot" style="animation-delay:.2s"></span><span class="dot" style="animation-delay:.4s"></span><span style="margin-left:8px;color:var(--muted)">${user_role || 'User'} is typing…</span>`;
    messagesEl.appendChild(el);
    el.scrollIntoView({ behavior:'smooth', block:'end' });
    typingTimeout = setTimeout(()=> document.getElementById('typingIndicator')?.remove(), 2500);
  }

  /* Refresh & init */
  refreshBtn?.addEventListener('click', loadConversations);
  loadConversations();
});
