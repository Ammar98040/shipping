(function (w) {
  w.getFormActionUrl = function (form) {
    var attr = form && form.getAttribute ? String(form.getAttribute('action') || '').trim() : '';
    return attr || w.location.href;
  };

  /** نسخ نص مع دعم الحافظة الحديثة وfallback لـ execCommand */
  w.copyTextToClipboard = function (text, onSuccess) {
    text = String(text || '').trim();
    if (!text) return;
    function done() {
      if (typeof onSuccess === 'function') onSuccess();
    }
    function fallbackCopy() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        done();
      } catch (e) {}
      document.body.removeChild(ta);
    }
    if (w.navigator.clipboard && w.navigator.clipboard.writeText) {
      w.navigator.clipboard.writeText(text).then(done).catch(fallbackCopy);
      return;
    }
    fallbackCopy();
  };
})(window);
