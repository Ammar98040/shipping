/**
 * خانات OTP: إدخال من اليسار لليمين مع الانتقال التلقائي (بدون Tab).
 * يدعم لوحة الأرقام، اللصق، والمفاتيح التي لا ترسل keydown واضحاً (جوال).
 */
(function (w) {
  'use strict';

  function focusBox(boxes, i) {
    var b = boxes[i];
    if (!b) return;
    w.requestAnimationFrame(function () {
      try {
        b.focus({ preventScroll: false });
        if (typeof b.select === 'function') b.select();
      } catch (e) {
        b.focus();
      }
    });
  }

  function setFilled(el, on) {
    if (el && el.classList) el.classList.toggle('filled', !!on);
  }

  w.initOtpInputs = function (container, digitSelector, opts) {
    if (!container || !digitSelector) return;
    opts = opts || {};
    var n = opts.length || 6;
    var minLen = opts.minLength != null ? opts.minLength : n;
    var boxes = Array.prototype.slice.call(container.querySelectorAll(digitSelector));
    if (!boxes.length) return;

    var hidden = opts.hiddenInput || null;
    var submitBtn = opts.submitButton || null;
    var autoFirst = opts.autocompleteFirst !== undefined ? opts.autocompleteFirst : 'one-time-code';

    function sync() {
      var v = '';
      boxes.forEach(function (b) {
        v += String(b.value || '').replace(/\D/g, '').charAt(0);
      });
      if (hidden) hidden.value = v;
      if (submitBtn) submitBtn.disabled = v.length < minLen;
      return v;
    }

    function applyDigitAt(i, ch) {
      if (!/^\d$/.test(ch)) return;
      var b = boxes[i];
      if (!b) return;
      b.value = ch;
      setFilled(b, true);
      sync();
      if (i < boxes.length - 1) focusBox(boxes, i + 1);
      else if (submitBtn && !submitBtn.disabled) submitBtn.focus();
    }

    function distributeDigits(str) {
      var digits = String(str || '').replace(/\D/g, '').slice(0, n);
      if (!digits) return;
      boxes.forEach(function (b, idx) {
        var d = digits.charAt(idx);
        b.value = d;
        setFilled(b, !!d);
      });
      sync();
      var lastIdx = Math.min(digits.length, n) - 1;
      focusBox(boxes, lastIdx < 0 ? 0 : lastIdx);
    }

    boxes.forEach(function (box, i) {
      box.setAttribute('inputmode', 'numeric');
      box.setAttribute('maxlength', '1');
      box.setAttribute('autocomplete', i === 0 ? autoFirst : 'off');

      box.addEventListener('keydown', function (e) {
        if (e.key === 'Backspace') {
          e.preventDefault();
          if (box.value) {
            box.value = '';
            setFilled(box, false);
            sync();
          } else if (i > 0) {
            boxes[i - 1].value = '';
            setFilled(boxes[i - 1], false);
            sync();
            focusBox(boxes, i - 1);
          }
          return;
        }
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          if (i > 0) focusBox(boxes, i - 1);
          return;
        }
        if (e.key === 'ArrowRight') {
          e.preventDefault();
          if (i < boxes.length - 1) focusBox(boxes, i + 1);
          return;
        }
        if (e.key === 'Tab' || e.key === 'Enter') return;

        var k = e.key;
        if (k.length === 1 && k >= '0' && k <= '9') {
          e.preventDefault();
          applyDigitAt(i, k);
          return;
        }
        var m = e.code && /^Numpad(\d)$/.exec(e.code);
        if (m) {
          e.preventDefault();
          applyDigitAt(i, m[1]);
        }
      });

      box.addEventListener('input', function () {
        var raw = String(box.value || '').replace(/\D/g, '');
        if (raw.length > 1) {
          distributeDigits(raw);
          return;
        }
        var one = raw.slice(0, 1);
        box.value = one;
        setFilled(box, !!one);
        sync();
        if (one && i < boxes.length - 1) focusBox(boxes, i + 1);
      });

      box.addEventListener('paste', function (e) {
        var text = (e.clipboardData || w.clipboardData).getData('text') || '';
        var d = text.replace(/\D/g, '');
        if (d.length >= 2) {
          e.preventDefault();
          distributeDigits(text);
        }
      });
    });

    container.addEventListener(
      'paste',
      function (e) {
        if (!container.contains(e.target)) return;
        var text = (e.clipboardData || w.clipboardData).getData('text') || '';
        if (text.replace(/\D/g, '').length >= 2) {
          e.preventDefault();
          distributeDigits(text);
        }
      },
      true
    );

    sync();
    focusBox(boxes, 0);
  };
})(window);
