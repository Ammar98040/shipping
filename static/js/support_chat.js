(function () {
  function getCookie(name) {
    try {
      const cookieStr = document.cookie || '';
      const parts = cookieStr.split(';').map(p => p.trim());
      for (const p of parts) {
        if (p.startsWith(name + '=')) return decodeURIComponent(p.substring(name.length + 1));
      }
    } catch (e) {}
    return null;
  }

  function escHtml(str) {
    return String(str)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  const app = document.getElementById('supportChatApp');
  if (!app) return;

  const pollUrl = app.getAttribute('data-poll-url');
  const sendUrl = app.getAttribute('data-send-url');
  const endUrl = app.getAttribute('data-end-url');
  const viewerLabel = app.getAttribute('data-viewer-label') || 'العميل';
  const staffLabel = app.getAttribute('data-staff-label') || 'خدمة العملاء';
  const botLabel = app.getAttribute('data-bot-label') || 'المساعد الآلي';
  const sendUrlForQuick = sendUrl;

  const bannerEl = document.getElementById('supportBanner');
  const messagesEl = document.getElementById('supportMessages');
  const endNoticeEl = document.getElementById('supportEndNotice');
  const newChatWrapEl = document.getElementById('supportNewChatWrap');
  const SCROLL_BOTTOM_THRESHOLD_PX = 80;
  let lastMessagesSig = '';
  let forceScrollAfterAction = false;
  /** آخر حالة وصلنا إليها من الـ API — للكشف عن الانتقال إلى ended (إظهار «محادثة جديدة» مرة واحدة) */
  let lastThreadStatus = (app.getAttribute('data-initial-status') || '').trim();

  const inputEl = document.getElementById('supportMessageInput');
  const sendBtn = document.getElementById('supportSendBtn');
  const sendBtnMobile = document.getElementById('supportSendBtnMobile');
  const imageInput = document.getElementById('supportImageInput');
  const previewBox = document.getElementById('supportPreviewBox');
  const previewGrid = document.getElementById('supportPreviewGrid');
  const previewName = document.getElementById('supportPreviewName');
  const previewClear = document.getElementById('supportPreviewClear');
  const endBtn = document.getElementById('supportEndBtn');

  /**
   * زر «محادثة جديدة» للضيف: يظهر فقط عند الانتقال من محادثة حيّة (active / waiting_for_staff)
   * إلى ended — مثلاً بعد الضغط على «إنهاء». لا يُعرض في أي حالة أخرى.
   * ملاحظة: سمة hidden تحتاج إخفاءً قوياً في CSS لأن flex قد يُلغيها.
   */
  function updateGuestNewChatCta(prevStatus, nextStatus) {
    if (!newChatWrapEl || !app) return;
    if (app.getAttribute('data-is-guest') !== '1') {
      newChatWrapEl.hidden = true;
      return;
    }
    const prev = (prevStatus || '').trim();
    const next = (nextStatus || '').trim();
    const fromLive = prev === 'active' || prev === 'waiting_for_staff';
    const show = next === 'ended' && fromLive;
    newChatWrapEl.hidden = !show;
  }

  function setBanner(status) {
    if (!bannerEl) return;
    if (status === 'waiting_for_staff') bannerEl.textContent = 'بانتظار ممثل خدمة العملاء...';
    else if (status === 'active') bannerEl.textContent = 'تم الاتصال. اكتب رسالتك الآن.';
    else if (status === 'ended') bannerEl.textContent = 'المحادثة منتهية. يمكنك إرسال رسالة لبدء محادثة جديدة.';
    else bannerEl.textContent = 'خدمة العملاء';
  }

  function setEndedState(threadStatus) {
    if (threadStatus === 'ended') {
      if (endBtn) endBtn.style.display = 'none';
      if (sendBtn) sendBtn.disabled = false;
      if (inputEl) inputEl.disabled = false;
    } else {
      if (endBtn) endBtn.style.display = 'inline-block';
      if (sendBtn) sendBtn.disabled = false;
      if (inputEl) inputEl.disabled = false;
    }
  }

  function setEndNotice(text) {
    if (!endNoticeEl) return;
    const value = (text || '').trim();
    if (value) {
      endNoticeEl.hidden = false;
      endNoticeEl.textContent = value;
    } else {
      endNoticeEl.hidden = true;
      endNoticeEl.textContent = '';
    }
  }

  function messagesSignature(messages) {
    return (messages || []).map(function (m) {
      return [m.id, m.text, m.image_url, JSON.stringify(m.quick_replies || []), m.created_at].join('\x1F');
    }).join('\x1E');
  }

  function renderMessages(messages, opts) {
    if (!messagesEl) return;
    opts = opts || {};
    const wantBottom = opts.forceScrollBottom === true;
    const sig = messagesSignature(messages);
    if (sig === lastMessagesSig) {
      if (wantBottom) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      return;
    }

    const oldH = messagesEl.scrollHeight;
    const oldTop = messagesEl.scrollTop;
    const ch = messagesEl.clientHeight;
    const atBottom = oldH - oldTop - ch < SCROLL_BOTTOM_THRESHOLD_PX;
    const stickBottom = wantBottom || !lastMessagesSig || atBottom;

    messagesEl.innerHTML = '';
    for (const m of messages) {
      const isBot = m.is_bot === true;
      const cls =
        m.sender_type === 'customer' ? 'support-msg--customer' :
        m.sender_type === 'staff' ? 'support-msg--staff' :
        isBot ? 'support-msg--bot' : 'support-msg--system';

      const time = m.created_at ? new Date(m.created_at).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }) : '';
      let senderLabel = m.sender_type === 'customer' ? viewerLabel : staffLabel;
      if (isBot) senderLabel = botLabel;
      const bubble = document.createElement('div');
      const text = m.text || '';
      const imageUrl = m.image_url || '';
      const imageOnly = imageUrl && !text.trim();
      bubble.className = 'support-msg ' + cls + (imageOnly ? ' support-msg--image-only' : '');
      let html = `<div class="support-msg-sender${imageOnly ? ' support-msg-sender--image' : ''}">${escHtml(senderLabel)}</div>`;
      if (text) html += `<div class="support-msg-text">${escHtml(text).replaceAll('\n', '<br>')}</div>`;
      if (imageUrl) {
        html += `<div class="support-msg-image-wrap${imageOnly ? ' support-msg-image-wrap--timed' : ''}"><a href="${escHtml(imageUrl)}" target="_blank" rel="noopener"><img class="support-msg-image" src="${escHtml(imageUrl)}" alt="صورة مرفقة"></a>`;
        if (imageOnly && time) html += `<div class="support-msg-meta support-msg-meta--overlay">${escHtml(time)}</div>`;
        html += `</div>`;
      }
      if ((!imageOnly || !imageUrl) && time) html += `<div class="support-msg-meta">${escHtml(time)}</div>`;
      bubble.innerHTML = html;
      const qrs = m.quick_replies;
      if (isBot && Array.isArray(qrs) && qrs.length && inputEl) {
        const row = document.createElement('div');
        row.className = 'support-quick-replies';
        for (const q of qrs) {
          const lab = (q && q.label) ? String(q.label) : '';
          if (!lab) continue;
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'support-qr-btn';
          b.textContent = lab;
          b.addEventListener('click', async function () {
            if (!sendUrlForQuick) return;
            inputEl.value = lab;
            sendBtn && sendBtn.click();
          });
          row.appendChild(b);
        }
        bubble.appendChild(row);
      }
      messagesEl.appendChild(bubble);
    }
    lastMessagesSig = sig;
    const newH = messagesEl.scrollHeight;
    if (stickBottom) {
      messagesEl.scrollTop = newH;
    } else {
      messagesEl.scrollTop = Math.max(0, oldTop + (newH - oldH));
    }
  }

  function clearPreview() {
    if (imageInput) imageInput.value = '';
    if (previewGrid) previewGrid.innerHTML = '';
    if (previewName) previewName.textContent = '';
    if (previewBox) previewBox.hidden = true;
  }

  function renderPreview(files) {
    if (!previewGrid || !previewName || !previewBox) return;
    previewGrid.innerHTML = '';
    const imageFiles = (files || []).filter(function (file) {
      return file && file.type && file.type.indexOf('image/') === 0;
    });
    if (!imageFiles.length) {
      clearPreview();
      return;
    }
    imageFiles.forEach(function (file) {
      const reader = new FileReader();
      reader.onload = function (ev) {
        const img = document.createElement('img');
        img.className = 'support-preview-image';
        img.alt = 'معاينة الصورة';
        img.src = (ev.target && ev.target.result) ? ev.target.result : '';
        previewGrid.appendChild(img);
      };
      reader.readAsDataURL(file);
    });
    previewName.textContent = imageFiles.length === 1 ? (imageFiles[0].name || '') : (imageFiles.length + ' صور محددة');
    previewBox.hidden = false;
  }

  async function poll() {
    if (!pollUrl) return;
    try {
      const res = await fetch(pollUrl, { method: 'GET', credentials: 'same-origin' });
      const data = await res.json();
      if (!data.success) {
        if (data.error === 'phone_required') {
          // لا حاجة: الصفحة أصلًا تعرض فورم رقم الجوال
        }
        return;
      }

      const st = (data.thread && data.thread.status) || '';
      const prevSt = lastThreadStatus;
      setBanner(st);
      setEndedState(st);
      updateGuestNewChatCta(prevSt, st);
      lastThreadStatus = st;
      setEndNotice((data.thread && data.thread.end_message) || '');
      const ropts = { forceScrollBottom: forceScrollAfterAction };
      forceScrollAfterAction = false;
      renderMessages(data.messages || [], ropts);
    } catch (e) {
      // ignore
    }
  }

  let pollTimer = null;
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    poll();
    pollTimer = setInterval(poll, 3500);
  }

  if (sendBtn && inputEl) {
    sendBtn.addEventListener('click', async function () {
      const text = (inputEl.value || '').trim();
      const files = imageInput && imageInput.files ? Array.prototype.slice.call(imageInput.files) : [];
      if (!text && !files.length) return;
      sendBtn.disabled = true;
      if (sendBtnMobile) sendBtnMobile.disabled = true;

      try {
        const csrf = getCookie('csrftoken');
        const body = new FormData();
        body.set('message', text);
        files.forEach(function (file) {
          body.append('image', file);
        });
        await fetch(sendUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': csrf || ''
          },
          body
        });
        inputEl.value = '';
        clearPreview();
        forceScrollAfterAction = true;
        await poll();
      } catch (e) {
        // ignore
      } finally {
        sendBtn.disabled = false;
        if (sendBtnMobile) sendBtnMobile.disabled = false;
      }
    });
  }
  if (sendBtnMobile && inputEl) {
    sendBtnMobile.addEventListener('click', function () {
      sendBtn && sendBtn.click();
    });
  }
  if (imageInput) {
    imageInput.addEventListener('change', function () {
      const files = imageInput.files ? Array.prototype.slice.call(imageInput.files) : [];
      renderPreview(files);
    });
  }
  if (previewClear) {
    previewClear.addEventListener('click', clearPreview);
  }

  if (inputEl) {
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendBtn && sendBtn.click();
      }
    });
  }

  if (endBtn) {
    endBtn.addEventListener('click', async function () {
      try {
        const csrf = getCookie('csrftoken');
        await fetch(endUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrf || ''
          },
          body: ''
        });
      } catch (e) {
        // ignore
      }
      forceScrollAfterAction = true;
      await poll();
    });
  }

  startPolling();
})();

