document.addEventListener('DOMContentLoaded', function () {
  const fields = document.querySelectorAll('.auth-field');
  if (!fields.length) return;

  function refreshState(wrapper) {
    const control = wrapper.querySelector('input, textarea, select');
    if (!control) return;
    const hasValue = !!(control.value && control.value.toString().trim().length);
    wrapper.classList.toggle('is-active', hasValue || document.activeElement === control);
  }

  fields.forEach((wrapper) => {
    const control = wrapper.querySelector('input, textarea, select');
    if (!control) return;

    control.placeholder = ' ';

    control.addEventListener('focus', function () {
      wrapper.classList.add('is-active');
    });
    control.addEventListener('blur', function () {
      refreshState(wrapper);
    });
    control.addEventListener('input', function () {
      refreshState(wrapper);
    });

    refreshState(wrapper);
  });
});
