(function () {
    'use strict';
    // دولابك - base.js (يمكن إضافة تفاعلات لاحقاً)
    if (!window.getFormActionUrl) {
        window.getFormActionUrl = function (form) {
            if (!form || typeof form.getAttribute !== 'function') return window.location.href;
            var attr = String(form.getAttribute('action') || '').trim();
            return attr || window.location.href;
        };
    }
})();
