(function () {
    'use strict';

    // تأثيرات التنقل بين الصفحات (فتح/غلق الأبواب)
    
    document.addEventListener('DOMContentLoaded', function () {
        // عند الدخول للصفحة من الدولاب - تأثير فتح الباب
        const isFromWardrobe = document.referrer.includes('/') && 
                               !document.referrer.includes('/compartment/') &&
                               !document.referrer.includes('/shelf/');
        
        if (isFromWardrobe) {
            document.body.style.animation = 'pageSlideIn 0.6s ease-out';
        }

        // عند الضغط على "رجوع للدولاب" - تأثير إغلاق
        const backLinks = document.querySelectorAll('[data-back-to-wardrobe]');
        backLinks.forEach(function (link) {
            link.addEventListener('click', function (e) {
                e.preventDefault();
                const url = link.getAttribute('href');
                
                document.body.style.animation = 'pageSlideOut 0.5s ease-in forwards';
                
                setTimeout(function () {
                    window.location.href = url;
                }, 450);
            });
        });
    });

    // أنيميشن دخول الصفحة
    const style = document.createElement('style');
    style.textContent = `
        @keyframes pageSlideIn {
            from {
                opacity: 0;
                transform: scale(0.95) translateY(20px);
            }
            to {
                opacity: 1;
                transform: scale(1) translateY(0);
            }
        }
        
        @keyframes pageSlideOut {
            from {
                opacity: 1;
                transform: scale(1);
            }
            to {
                opacity: 0;
                transform: scale(1.05);
            }
        }
    `;
    document.head.appendChild(style);
})();
