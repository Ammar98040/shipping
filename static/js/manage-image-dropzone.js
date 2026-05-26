/**
 * مساحة سحب وإفلات للصور في نماذج الإدارة (خانات، رفوف، أصناف، منتجات).
 * يعمل مع الحقل الأصلي type=file ويرسل مع نفس النموذج.
 */
(function () {
  'use strict';

  function isImageFile(file) {
    return file && typeof file.type === 'string' && file.type.indexOf('image/') === 0;
  }

  function assignFile(input, file) {
    if (!file || !isImageFile(file)) return false;
    var dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  function initFileInput(input) {
    if (input.dataset.manageDndInit) return;
    if (input.type !== 'file') return;
    input.dataset.manageDndInit = '1';

    var formGroup = input.closest('.form-group');
    if (!formGroup) return;

    var shell = document.createElement('div');
    shell.className = 'manage-image-dnd-shell';

    var zone = document.createElement('div');
    zone.className = 'manage-dropzone';
    zone.setAttribute('tabindex', '0');
    zone.setAttribute('role', 'button');

    var hint = document.createElement('div');
    hint.className = 'manage-dropzone__hint';
    hint.innerHTML =
      '<span class="manage-dropzone__icon" aria-hidden="true">📷</span>' +
      '<span class="manage-dropzone__title">اسحب الصورة وأفلتها هنا</span>' +
      '<span class="manage-dropzone__sub">أو انقر لاختيار ملف من جهازك</span>';

    var preview = document.createElement('div');
    preview.className = 'manage-dropzone__preview';
    var previewImg = document.createElement('img');
    previewImg.alt = '';
    previewImg.className = 'manage-dropzone__preview-img';
    preview.appendChild(previewImg);

    var nameEl = document.createElement('div');
    nameEl.className = 'manage-dropzone__filename';
    nameEl.setAttribute('aria-live', 'polite');

    zone.appendChild(hint);
    zone.appendChild(preview);
    zone.appendChild(nameEl);

    input.classList.add('manage-dropzone-native-input');

    var parent = input.parentNode;
    parent.insertBefore(shell, input);
    shell.appendChild(input);
    shell.appendChild(zone);

    function uncheckClear() {
      var cb = formGroup.querySelector('input[type="checkbox"][name$="-clear"]');
      if (cb) cb.checked = false;
    }

    function revokePreview() {
      if (previewImg._objUrl) {
        URL.revokeObjectURL(previewImg._objUrl);
        previewImg._objUrl = null;
      }
    }

    function updatePreview(file) {
      revokePreview();
      if (file && isImageFile(file)) {
        previewImg._objUrl = URL.createObjectURL(file);
        previewImg.src = previewImg._objUrl;
        zone.classList.add('has-file');
        nameEl.textContent = file.name;
      } else if (input.files && input.files.length && isImageFile(input.files[0])) {
        var f = input.files[0];
        previewImg._objUrl = URL.createObjectURL(f);
        previewImg.src = previewImg._objUrl;
        zone.classList.add('has-file');
        nameEl.textContent = f.name;
      } else {
        previewImg.removeAttribute('src');
        zone.classList.remove('has-file');
        nameEl.textContent = '';
      }
    }

    if (input.files && input.files.length) {
      updatePreview(input.files[0]);
    }

    zone.addEventListener('click', function () {
      input.click();
    });
    zone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.click();
      }
    });

    input.addEventListener('change', function () {
      uncheckClear();
      if (input.files && input.files.length) updatePreview(input.files[0]);
      else {
        revokePreview();
        previewImg.removeAttribute('src');
        zone.classList.remove('has-file');
        nameEl.textContent = '';
      }
    });

    var dragDepth = 0;
    zone.addEventListener('dragenter', function (e) {
      e.preventDefault();
      e.stopPropagation();
      dragDepth += 1;
      zone.classList.add('is-dragover');
    });
    zone.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'copy';
      zone.classList.add('is-dragover');
    });
    zone.addEventListener('dragleave', function (e) {
      e.preventDefault();
      e.stopPropagation();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) zone.classList.remove('is-dragover');
    });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      e.stopPropagation();
      dragDepth = 0;
      zone.classList.remove('is-dragover');
      var f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (assignFile(input, f)) {
        uncheckClear();
        updatePreview(f);
      }
    });
  }

  function initAll(root) {
    root = root || document;
    root.querySelectorAll('form.manage-form--dnd-images input[type="file"]').forEach(initFileInput);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initAll(document);
  });
})();
