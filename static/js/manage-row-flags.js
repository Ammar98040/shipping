/**
 * إزالة علامة «جديد» عند النقر على صف يحمل data-manage-row-key.
 */
(function () {
  'use strict';

  function getCsrf() {
    if (typeof window.MANAGE_CSRF_TOKEN === 'string' && window.MANAGE_CSRF_TOKEN) {
      var injected = window.MANAGE_CSRF_TOKEN.trim();
      // Django قد يحقن "NOTPROVIDED" أو "csrf_token" عندما لا يتوفر التوكن.
      if (injected && injected !== 'NOTPROVIDED' && injected !== 'csrf_token') {
        return injected;
      }
    }
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1].trim()) : '';
  }

  function markUrl() {
    return (typeof window.MANAGE_MARK_SEEN_URL === 'string' && window.MANAGE_MARK_SEEN_URL)
      ? window.MANAGE_MARK_SEEN_URL
      : '/manage/api/mark-seen/';
  }

  function bulkUrl() {
    return (typeof window.MANAGE_MARK_SEEN_BULK_URL === 'string' && window.MANAGE_MARK_SEEN_BULK_URL)
      ? window.MANAGE_MARK_SEEN_BULK_URL
      : '/manage/api/mark-seen-bulk/';
  }

  function clearRowVisual(row) {
    row.classList.remove('manage-row--new');
    row.classList.remove('manage-row--updated');
    var dot = row.querySelector('.manage-row-new-dot');
    if (dot) dot.remove();
  }

  function postMarkSeen(key) {
    return fetch(markUrl(), {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({ key: key }),
      keepalive: true, // بديل sendBeacon مع دعم رؤوس الطلب (CSRF)
    });
  }

  function sendMarkSeen(key) {
    // fetch مع keepalive يدعم رأس CSRF (على عكس sendBeacon) — مطلوب عند عدم استخدام csrf_exempt.
    postMarkSeen(key).catch(function () {});
  }

  function postMarkSeenBulk(keys) {
    return fetch(bulkUrl(), {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({ keys: keys }),
      keepalive: true,
    });
  }

  document.body.addEventListener(
    'pointerdown',
    function (e) {
      var row = e.target.closest('tr[data-manage-row-key].manage-row--new, tr[data-manage-row-key].manage-row--updated');
      if (!row) return;
      var key = row.getAttribute('data-manage-row-key');
      if (!key) return;
      clearRowVisual(row);
      sendMarkSeen(key);
    },
    true
  );

  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-manage-mark-visible]');
    if (!btn) return;
    e.preventDefault();
    var scopeSel = btn.getAttribute('data-manage-mark-visible');
    var scope = scopeSel ? document.querySelector(scopeSel) : document;
    var root = scope || document;
    var rows = root.querySelectorAll('tr[data-manage-row-key].manage-row--new, tr[data-manage-row-key].manage-row--updated');
    if (!rows.length) return;
    var keys = [];
    rows.forEach(function (row) {
      var key = row.getAttribute('data-manage-row-key');
      if (key) keys.push(key);
      clearRowVisual(row);
    });
    postMarkSeenBulk(keys).catch(function () {});
  });
})();
