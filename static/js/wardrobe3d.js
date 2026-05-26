(function () {
    'use strict';

    // تفاعل أبواب الدولاب ثلاثي الأبعاد
    document.addEventListener('DOMContentLoaded', function () {
        const doors = document.querySelectorAll('.compartment-door-link');

        doors.forEach(function (doorLink) {
            doorLink.addEventListener('click', function (e) {
                e.preventDefault();
                const slot = doorLink.closest('.compartment-slot');
                const url = doorLink.getAttribute('href');

                // منع النقر المتعدد
                if (slot.classList.contains('opening')) return;

                // إضافة كلاس "فتح الباب"
                slot.classList.add('opening');

                // الانتظار حتى تنتهي الأنيميشن ثم الانتقال
                setTimeout(function () {
                    window.location.href = url;
                }, 700);
            });

            // تأثير صوتي بصري عند التمرير
            doorLink.addEventListener('mouseenter', function () {
                const panel = this.querySelector('.door-panel');
                if (panel) {
                    panel.style.transform = 'scale(1.02)';
                    setTimeout(() => {
                        panel.style.transform = '';
                    }, 150);
                }
            });
        });

        // تأثير تحميل الصفحة
        const wardrobe = document.querySelector('.wardrobe-3d');
        if (wardrobe) {
            setTimeout(() => {
                wardrobe.style.opacity = '1';
            }, 100);
        }
    });
})();
