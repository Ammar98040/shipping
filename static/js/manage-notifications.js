/**
 * عدّادات تنبيهات لوحة الإدارة + تحديث تلقائي للمحتوى (بدون إعادة تحميل يدوية).
 */
(function () {
  'use strict';

  var POLL_MS = (typeof window.MANAGE_NOTIFICATIONS_POLL_MS === 'number' && window.MANAGE_NOTIFICATIONS_POLL_MS >= 5000)
    ? window.MANAGE_NOTIFICATIONS_POLL_MS
    : 8000;
  var url = (typeof window.MANAGE_NOTIFICATIONS_URL === 'string' && window.MANAGE_NOTIFICATIONS_URL)
    ? window.MANAGE_NOTIFICATIONS_URL
    : '/manage/api/notifications/';
  var lastSnapshot = null;
  var pollTimer = null;

  function badgeEl(key) {
    return document.querySelectorAll('[data-manage-badge="' + key + '"]');
  }

  function setBadge(key, n) {
    var els = badgeEl(key);
    if (!els || !els.length) return;
    var v = parseInt(n, 10) || 0;
    els.forEach(function (el) {
      if (v <= 0) {
        el.textContent = '';
        el.setAttribute('hidden', 'hidden');
        return;
      }
      if (el.classList.contains('manage-nav-dot')) {
        el.textContent = '';
      } else {
        el.textContent = String(v);
      }
      el.removeAttribute('hidden');
    });
  }

  function renderActivity(events) {
    var box = document.getElementById('manage-activity-list');
    if (!box) return;
    function esc(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }
    var rows = Array.isArray(events) ? events : [];
    if (!rows.length) {
      box.innerHTML = '<div class="manage-activity-empty">لا توجد أحداث حديثة.</div>';
      return;
    }
    var html = rows
      .map(function (e) {
        var label = (e && e.label) ? esc(e.label) : 'حدث جديد';
        var when = (e && e.when) ? String(e.when).replace('T', ' ').slice(0, 16) : '';
        var url = (e && e.url) ? esc(e.url) : '#';
        return (
          '<a class="manage-activity-item" href="' + url + '">' +
            '<span class="manage-activity-label">' + label + '</span>' +
            '<span class="manage-activity-time">' + when + '</span>' +
          '</a>'
        );
      })
      .join('');
    box.innerHTML = html;
  }

  function snapshotFromPayload(data) {
    if (!data || !data.counts || !data.dashboard) return '';
    return JSON.stringify({
      c: data.counts,
      d: data.dashboard,
      os: data.order_stats,
      rs: data.returns_stats,
    });
  }

  function applyPayload(data) {
    if (!data || !data.counts) return;
    if (data.ui && data.ui.poll_ms) {
      var next = parseInt(data.ui.poll_ms, 10);
      if (next >= 5000 && next !== POLL_MS) {
        POLL_MS = next;
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = setInterval(poll, POLL_MS);
        }
      }
    }
    var c = data.counts;
    setBadge('orders', c.orders);
    setBadge('users', c.users_new);
    setBadge('returns', c.returns);
    setBadge('warehouse', c.warehouse);
    setBadge('shipments', c.shipments);
    setBadge('contact', c.contact);
    setBadge('support', c.support);
    setBadge('catalog_group', c.users_new);
    setBadge('sales_group', (parseInt(c.orders, 10) || 0) + (parseInt(c.returns, 10) || 0));
    setBadge('logistics_group', (parseInt(c.shipments, 10) || 0) + (parseInt(c.warehouse, 10) || 0));
    setBadge('support_group', (parseInt(c.contact, 10) || 0) + (parseInt(c.support, 10) || 0));
    renderActivity(data.recent_events);

    var snap = snapshotFromPayload(data);
    if (lastSnapshot !== null && snap !== lastSnapshot && snap.length) {
      try {
        document.dispatchEvent(new CustomEvent('manage:countsChanged', { detail: data }));
      } catch (e) {}
    }
    lastSnapshot = snap;
  }

  function poll() {
    fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
    })
      .then(function (r) {
        if (!r.ok) throw new Error('bad status');
        return r.json();
      })
      .then(applyPayload)
      .catch(function () {});
  }

  function start() {
    if (!document.body || !document.body.classList.contains('manage-body')) return;
    poll();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(poll, POLL_MS);

  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
