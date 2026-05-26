(function () {
  const app = document.getElementById('manageSupportThreadApp');
  if (!app) return;

  const pollUrl = app.getAttribute('data-poll-url');
  const sendUrl = app.getAttribute('data-send-url');
  const endUrl = app.getAttribute('data-end-url');
  const claimUrl = app.getAttribute('data-claim-url') || '';
  const markReadUrl = app.getAttribute('data-mark-read-url') || '';
  const customerLabel = app.getAttribute('data-customer-label') || 'العميل';
  const staffLabel = app.getAttribute('data-staff-label') || 'خدمة العملاء';
  const botLabel = app.getAttribute('data-bot-label') || 'المساعد الآلي';

  const bannerEl = document.getElementById('manageSupportBanner');
  const messagesEl = document.getElementById('manageSupportMessages');
  const endNoticeEl = document.getElementById('manageSupportEndNotice');
  const SCROLL_BOTTOM_THRESHOLD_PX = 80;
  let lastMessagesSig = '';
  let forceScrollAfterAction = false;
  const statusDisplayEl = document.getElementById('manageSupportStatusDisplay');
  const inputEl = document.getElementById('manageSupportMessageInput');
  const sendBtn = document.getElementById('manageSupportSendBtn');
  const sendBtnMobile = document.getElementById('manageSupportSendBtnMobile');
  const imageInput = document.getElementById('manageSupportImageInput');
  const previewBox = document.getElementById('manageSupportPreviewBox');
  const previewGrid = document.getElementById('manageSupportPreviewGrid');
  const previewName = document.getElementById('manageSupportPreviewName');
  const previewClear = document.getElementById('manageSupportPreviewClear');
  const endBtn = document.getElementById('manageSupportEndBtn');
  const claimWrap = document.getElementById('manageSupportClaimWrap');
  const claimBtn = document.getElementById('manageSupportClaimBtn');

  function escHtml(str) {
    return String(str)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function setBanner(status) {
    if (!bannerEl) return;
    if (status === 'waiting_for_staff') bannerEl.textContent = 'بانتظار تفعيل الرسائل...';
    else if (status === 'active') bannerEl.textContent = 'المحادثة نشطة.';
    else if (status === 'ended') bannerEl.textContent = 'المحادثة منتهية.';
    else bannerEl.textContent = '';
  }

  function setBannerExtended(thread) {
    if (!bannerEl || !thread) return;
    if (thread.send_blocked_until_claim === true) {
      bannerEl.textContent = 'اضغط «استلام المحادثة» قبل إرسال أي رد.';
      return;
    }
    if (thread.send_blocked_until_read === true) {
      bannerEl.textContent = 'يجب تأكيد قراءة جميع رسائل العميل قبل الإرسال.';
      return;
    }
    setBanner(thread.status);
  }

  function setClaimWrapVisibility(thread) {
    if (!claimWrap || !thread) return;
    claimWrap.hidden = thread.viewer_must_claim !== true;
  }

  function syncComposeFromThread(thread) {
    const ended = !thread || thread.status === 'ended';
    const blockClaim = thread && thread.send_blocked_until_claim === true;
    const blockRead = thread && thread.send_blocked_until_read === true;
    const allowCompose = !ended && !blockClaim && !blockRead;

    if (sendBtn) sendBtn.disabled = !allowCompose;
    if (sendBtnMobile) sendBtnMobile.disabled = !allowCompose;
    if (inputEl) inputEl.disabled = !allowCompose;
    if (imageInput) imageInput.disabled = !allowCompose;

    const lbl = document.querySelector('label.support-file-trigger[for="manageSupportImageInput"]');
    if (lbl) {
      lbl.style.opacity = allowCompose ? '' : '0.45';
      lbl.style.pointerEvents = allowCompose ? '' : 'none';
    }

    if (endBtn) endBtn.style.display = ended ? 'none' : 'inline-block';
  }

  function setStatusDisplay(statusText) {
    if (!statusDisplayEl) return;
    statusDisplayEl.textContent = (statusText || '').trim() || '-';
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
      let senderLabel = m.sender_type === 'customer' ? customerLabel : staffLabel;
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

  function postForm(url, bodyObj, files) {
    const csrf = window.MANAGE_CSRF_TOKEN || '';
    const body = new FormData();
    const obj = bodyObj || {};
    Object.keys(obj).forEach(function (k) {
      body.append(k, obj[k] || '');
    });
    (files || []).forEach(function (file) {
      body.append('image', file);
    });
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken': csrf
      },
      body
    });
  }

  async function postManageJson(url, bodyObj, files) {
    const res = await postForm(url, bodyObj || {}, files || []);
    let payload = {};
    try {
      payload = await res.json();
    } catch (e) {
      payload = {};
    }
    return { ok: res.ok, status: res.status, payload };
  }

  function applyPollPayload(data) {
    if (!data.success || !data.thread) return;
    const th = data.thread;
    setBannerExtended(th);
    setStatusDisplay(th.status_display || '');
    syncComposeFromThread(th);
    setClaimWrapVisibility(th);
    setEndNotice(th.end_message || '');
    renderMessages(data.messages || [], { forceScrollBottom: forceScrollAfterAction });
    forceScrollAfterAction = false;
  }

  async function pollOnce() {
    try {
      const res = await fetch(pollUrl, { method: 'GET', credentials: 'same-origin' });
      const data = await res.json();
      applyPollPayload(data);

      const th = data.thread;
      if (
        data.success
        && markReadUrl
        && th
        && th.enforce_read_before_send === true
        && th.viewer_is_assignee === true
        && th.all_customer_messages_read !== true
      ) {
        await postManageJson(markReadUrl, { mark_all: '1' });
        const res2 = await fetch(pollUrl, { method: 'GET', credentials: 'same-origin' });
        const data2 = await res2.json();
        applyPollPayload(data2);
      }
      return data;
    } catch (e) {
      return { success: false };
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

  async function onSend() {
    const text = (inputEl.value || '').trim();
    const files = imageInput && imageInput.files ? Array.prototype.slice.call(imageInput.files) : [];
    if (!text && !files.length) return;
    sendBtn && (sendBtn.disabled = true);
    sendBtnMobile && (sendBtnMobile.disabled = true);
    try {
      const { ok, payload } = await postManageJson(sendUrl, { message: text }, files);
      if (!ok) {
        const err = payload.error || '';
        if (err === 'must_claim_first') window.alert('استلم المحادثة أولاً قبل الإرسال.');
        else if (err === 'must_read_customer_messages') window.alert('يجب تأكيد قراءة جميع رسائل العميل قبل الإرسال.');
        else if (err === 'claimed_by_another_agent') window.alert('المحادثة مسندة لممثل آخر.');
        else window.alert('تعذّر الإرسال.');
        return;
      }
      inputEl.value = '';
      clearPreview();
      forceScrollAfterAction = true;
      await pollOnce();
    } catch (e) {
      // ignore
    } finally {
      sendBtn && (sendBtn.disabled = false);
      sendBtnMobile && (sendBtnMobile.disabled = false);
    }
  }

  async function onEnd() {
    try {
      await postManageJson(endUrl, {});
      forceScrollAfterAction = true;
      await pollOnce();
    } catch (e) {
      // ignore
    }
  }

  async function onClaim() {
    if (!claimUrl) return;
    if (claimBtn) claimBtn.disabled = true;
    try {
      const { ok, payload } = await postManageJson(claimUrl, {});
      if (!ok) {
        if (payload.error === 'claimed_by_another_agent') window.alert('سبق أن استلمها ممثل آخر.');
        else window.alert('تعذّر استلام المحادثة.');
        return;
      }
      forceScrollAfterAction = true;
      await pollOnce();
    } catch (e) {
      // ignore
    } finally {
      if (claimBtn) claimBtn.disabled = false;
    }
  }

  if (sendBtn) sendBtn.addEventListener('click', function (e) { e.preventDefault(); onSend(); });
  if (sendBtnMobile) sendBtnMobile.addEventListener('click', function (e) { e.preventDefault(); onSend(); });
  if (inputEl) inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onSend();
    }
  });
  if (endBtn) endBtn.addEventListener('click', function (e) { e.preventDefault(); onEnd(); });
  if (claimBtn) claimBtn.addEventListener('click', function (e) { e.preventDefault(); onClaim(); });
  if (imageInput) {
    imageInput.addEventListener('change', function () {
      const files = imageInput.files ? Array.prototype.slice.call(imageInput.files) : [];
      renderPreview(files);
    });
  }
  if (previewClear) {
    previewClear.addEventListener('click', clearPreview);
  }

  let t = null;
  function start() {
    pollOnce();
    t = setInterval(pollOnce, 3200);
  }
  start();
})();
