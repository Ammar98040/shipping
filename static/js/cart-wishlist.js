/**
 * إدارة السلة والمفضلة مع AJAX
 */

// الحصول على CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');

// عرض رسالة toast
function showToast(message, type = 'success') {
    // إزالة أي toast قديم
    const oldToast = document.querySelector('.toast-notification');
    if (oldToast) {
        oldToast.remove();
    }

    // إنشاء toast جديد
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // عرض Toast
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    // إخفاء وحذف Toast بعد 3 ثواني
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);
}

// تحديث عدد العناصر في الهيدر
function updateHeaderCounts(cartCount, wishlistCount) {
    // تحديث عدد السلة
    if (cartCount !== undefined) {
        let cartBadge = document.querySelector('.cart-badge');
        const cartLink = document.querySelector('.cart-link');
        
        if (!cartBadge && cartLink && cartCount > 0) {
            // إنشاء badge إذا لم يكن موجوداً
            cartBadge = document.createElement('span');
            cartBadge.className = 'header-badge cart-badge';
            cartLink.appendChild(cartBadge);
        }
        
        if (cartBadge) {
            cartBadge.textContent = cartCount;
            if (cartCount > 0) {
                cartBadge.style.display = 'flex';
            } else {
                cartBadge.style.display = 'none';
            }
        }
    }

    // تحديث عدد المفضلة
    if (wishlistCount !== undefined) {
        let wishlistBadge = document.querySelector('.wishlist-badge');
        const wishlistLink = document.querySelector('.wishlist-link');
        
        if (!wishlistBadge && wishlistLink && wishlistCount > 0) {
            // إنشاء badge إذا لم يكن موجوداً
            wishlistBadge = document.createElement('span');
            wishlistBadge.className = 'header-badge wishlist-badge';
            wishlistLink.appendChild(wishlistBadge);
        }
        
        if (wishlistBadge) {
            wishlistBadge.textContent = wishlistCount;
            if (wishlistCount > 0) {
                wishlistBadge.style.display = 'flex';
            } else {
                wishlistBadge.style.display = 'none';
            }
        }
    }
}

// إضافة منتج للسلة مع AJAX
function addToCart(productId, quantity = 1, buttonElement = null, variantId = '', selectedGalleryImageId = '') {
    const url = `/cart/add/${productId}/`;
    const formData = new FormData();
    formData.append('quantity', quantity);
    if (variantId) {
        formData.append('variant_id', variantId);
    }
    if (!variantId && selectedGalleryImageId) {
        formData.append('selected_gallery_image_id', selectedGalleryImageId);
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrftoken
        },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            updateHeaderCounts(data.cart_count, undefined);
            
            // تغيير لون الزر إلى أخضر
            if (buttonElement) {
                buttonElement.classList.add('in-cart', 'active-cart');
                buttonElement.title = 'في السلة';
            }
            
            // تحديث جميع أزرار نفس المنتج
            document.querySelectorAll(`[data-product-id="${productId}"].btn-add-to-cart-ajax`).forEach(btn => {
                btn.classList.add('in-cart', 'active-cart');
                btn.title = 'في السلة';
            });
        } else {
            showToast(data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ أثناء إضافة المنتج للسلة', 'error');
    });
}

// إضافة منتج للمفضلة مع AJAX
function addToWishlist(productId, buttonElement) {
    const url = `/wishlist/add/${productId}/`;

    fetch(url, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrftoken,
        },
        credentials: 'same-origin',
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, data.created ? 'success' : 'info');
            updateHeaderCounts(undefined, data.wishlist_count);
            
            // تغيير أيقونة الزر إلى أحمر
            if (buttonElement && data.created) {
                buttonElement.classList.add('in-wishlist', 'active-wishlist');
                buttonElement.innerHTML = '❤️';
                buttonElement.title = 'إزالة من المفضلة';
            }
            
            // تحديث جميع أزرار نفس المنتج
            document.querySelectorAll(`[data-product-id="${productId}"].btn-wishlist-ajax`).forEach(btn => {
                btn.classList.add('in-wishlist', 'active-wishlist');
                btn.innerHTML = '❤️';
                btn.title = 'إزالة من المفضلة';
            });
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('حدث خطأ أثناء إضافة المنتج للمفضلة', 'error');
    });
}

// إزالة بطاقة المنتج من صفحة المفضلات بدون إعادة تحميل الصفحة
function removeWishlistCardFromPageIfApplicable(buttonElement) {
    const itemsBlock = document.getElementById('wishlist-items-block');
    if (!itemsBlock || !buttonElement) return;
    const card = buttonElement.closest('.product-hanger');
    if (!card || !itemsBlock.contains(card)) return;

    card.remove();

    const grid = itemsBlock.querySelector('.products-display');
    const remaining = grid ? grid.querySelectorAll('.product-hanger').length : 0;

    const label = document.getElementById('wishlist-product-count-label');
    if (label) {
        label.textContent = `${remaining} منتج`;
    }

    if (remaining === 0) {
        itemsBlock.remove();
        const root = document.getElementById('wishlist-page-root');
        const tpl = document.getElementById('wishlist-empty-template');
        if (root && tpl && tpl.content && !root.querySelector('.wishlist-empty')) {
            root.appendChild(tpl.content.cloneNode(true));
        }
    }
}

// إزالة منتج من المفضلة مع AJAX (إزالة فورية على صفحة المفضلات + مزامنة مع الخادم)
function removeFromWishlist(productId, buttonElement) {
    let removedWishlistOptimistic = false;
    const wishlistShell = document.getElementById('wishlist-items-block');
    if (
        wishlistShell &&
        buttonElement &&
        wishlistShell.contains(buttonElement) &&
        buttonElement.classList.contains('in-wishlist')
    ) {
        removeWishlistCardFromPageIfApplicable(buttonElement);
        removedWishlistOptimistic = true;
    }

    const url = `/wishlist/remove/${productId}/`;

    fetch(url, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrftoken,
        },
        credentials: 'same-origin',
    })
        .then((response) => {
            const ct = (response.headers.get('content-type') || '').toLowerCase();
            if (!response.ok) {
                return Promise.reject(new Error('bad-status'));
            }
            if (!ct.includes('application/json')) {
                return Promise.reject(new Error('not-json'));
            }
            return response.json();
        })
        .then((data) => {
            if (!data || !data.success) {
                return Promise.reject(new Error('wishlist-remove-failed'));
            }

            if (!removedWishlistOptimistic) {
                removeWishlistCardFromPageIfApplicable(buttonElement);
            }

            showToast(data.message, 'success');
            updateHeaderCounts(undefined, data.wishlist_count);

            if (buttonElement && buttonElement.isConnected) {
                buttonElement.classList.remove('in-wishlist', 'active-wishlist');
                buttonElement.innerHTML = '🤍';
                buttonElement.title = 'إضافة للمفضلة';
            }

            document.querySelectorAll(`[data-product-id="${productId}"].btn-wishlist-ajax`).forEach((btn) => {
                btn.classList.remove('in-wishlist', 'active-wishlist');
                btn.innerHTML = '🤍';
                btn.title = 'إضافة للمفضلة';
            });
        })
        .catch((error) => {
            console.error('wishlist-remove', error);
            if (removedWishlistOptimistic) {
                window.location.reload();
                return;
            }
            showToast('تعذر تحديث المفضلات. تحقّق من الاتصال ثم حاول مرة أخرى.', 'error');
        });
}

// تفعيل الأزرار عند تحميل الصفحة
document.addEventListener('DOMContentLoaded', function() {
    // أزرار إضافة للسلة
    const cartButtons = document.querySelectorAll('.btn-add-to-cart-ajax');

    cartButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const productId = this.dataset.productId;
            const quantityInput = this.closest('form')?.querySelector('input[name="quantity"]');
            const quantity = quantityInput ? parseInt(quantityInput.value) : 1;
            const form = this.closest('form');
            const variantInput = form ? form.querySelector('input[name="variant_id"]') : null;
            const variantId = (this.dataset.variantId || (variantInput ? variantInput.value : '') || '').trim();
            const selectedGalleryImageInput = form ? form.querySelector('input[name="selected_gallery_image_id"]') : null;
            const selectedGalleryImageId = (selectedGalleryImageInput ? selectedGalleryImageInput.value : '').trim();
            addToCart(productId, quantity, this, variantId, selectedGalleryImageId);
        });
    });

    // المفضلة: استماع مُفَوَّض بمرحلة الالتقاط حتى لا يخطف الطبقة الرابط ضغطة القلب (خاصة على الموبايل)
    document.addEventListener(
        'click',
        function (e) {
            const btn = e.target.closest('.btn-wishlist-ajax');
            if (!btn) return;

            const productId = btn.dataset.productId;
            if (!productId) return;

            const isWishlistHeart = btn.classList.contains('in-wishlist');

            e.preventDefault();
            e.stopPropagation();

            if (isWishlistHeart) {
                removeFromWishlist(productId, btn);
            } else {
                addToWishlist(productId, btn);
            }
        },
        true,
    );
});