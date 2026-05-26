(function (w) {
  var ERR_STYLE = 'background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:12px;padding:0.75rem 1rem;margin:1rem 0;font-weight:800;';
  var OK_STYLE = 'background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0;border-radius:12px;padding:0.75rem 1rem;margin:1rem 0;font-weight:800;';

  w.showManageError = function (text, opts) {
    opts = opts || {};
    var ms = typeof opts.durationMs === 'number' ? opts.durationMs : 3500;
    var root = document.createElement('div');
    root.className = 'manage-message manage-message--error';
    root.style.cssText = ERR_STYLE;
    root.textContent = text || '';
    document.body.prepend(root);
    setTimeout(function () { root.remove(); }, ms);
  };

  w.showManageSuccess = function (text, opts) {
    opts = opts || {};
    var ms = typeof opts.durationMs === 'number' ? opts.durationMs : 2800;
    var root = document.createElement('div');
    root.className = 'manage-message manage-message--success';
    root.style.cssText = OK_STYLE;
    root.textContent = text || 'تم تنفيذ العملية بنجاح.';
    document.body.prepend(root);
    setTimeout(function () { root.remove(); }, ms);
  };
})(window);
