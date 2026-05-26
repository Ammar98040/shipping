/**
 * دولابك — حركات العملاء: GSAP (اختياري)، Three.js (خلفيات جزيئية خفيفة)، كشف عند التمرير.
 * متعدد الصفحات (Django): لا React — Three.js مباشرة، مكافئ لمحرك React Three Fiber.
 */
const THREE_ESM = 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js';
const GSAP_ESM = 'https://cdn.jsdelivr.net/npm/gsap@3.12.5/+esm';

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function saveData() {
    return navigator.connection && navigator.connection.saveData === true;
}

function storePathKey() {
    const raw = window.location.pathname.replace(/\/+$/, '');
    return raw === '' ? '/' : raw;
}

/** عناصر شائعة للكشف عند التمرير — لا نلمس لوحات الإدارة أو الشحن (قوالب أخرى). */
const REVEAL_SELECTOR = [
    '.product-hanger',
    '.shelf-item',
    '.order-card',
    '.return-card',
    '.review-card',
    '.profile-card',
    '.section-card',
    '.promo-spotlight',
    '.track-form-card',
    '.pay-card',
    '.support-phone-card',
].join(',');

async function loadGsap() {
    const mod = await import(/* webpackIgnore: true */ GSAP_ESM);
    return mod.gsap || mod.default;
}

async function loadThree() {
    return import(/* webpackIgnore: true */ THREE_ESM);
}

function markRevealTargets() {
    const main = document.querySelector('.main-content');
    if (!main) return [];

    const nodes = Array.from(main.querySelectorAll(REVEAL_SELECTOR)).filter(Boolean);
    const fold = window.innerHeight * 0.92;

    return nodes.filter((el) => {
        const r = el.getBoundingClientRect();
        return r.top > fold;
    });
}

function setupScrollReveal(gsap) {
    const targets = markRevealTargets();
    if (!targets.length) return;

    targets.forEach((el) => el.classList.add('store-reveal-target'));

    const revealOne = (el) => {
        if (gsap) {
            gsap.to(el, {
                opacity: 1,
                y: 0,
                duration: 0.55,
                ease: 'power2.out',
                onComplete: () => {
                    el.classList.add('is-revealed');
                    el.style.transform = '';
                    el.style.opacity = '';
                },
            });
        } else {
            requestAnimationFrame(() => el.classList.add('is-revealed'));
        }
    };

    if (!gsap) {
        const ioPlain = new IntersectionObserver(
            (entries, obs) => {
                entries.forEach((en) => {
                    if (!en.isIntersecting) return;
                    obs.unobserve(en.target);
                    en.target.classList.add('is-revealed');
                });
            },
            { root: null, rootMargin: '0px 0px -6% 0px', threshold: 0.08 },
        );
        targets.forEach((el) => ioPlain.observe(el));
        return;
    }

    gsap.set(targets, { opacity: 0, y: 18 });

    const io = new IntersectionObserver(
        (entries, obs) => {
            entries.forEach((en) => {
                if (!en.isIntersecting) return;
                obs.unobserve(en.target);
                revealOne(en.target);
            });
        },
        { root: null, rootMargin: '0px 0px -6% 0px', threshold: 0.08 },
    );

    targets.forEach((el) => io.observe(el));
}

/** دخول متدرّج لأقسام الصفحة الرئيسية (أسفل الهيرو). */
function runStaggerSections(gsap) {
    const main = document.querySelector('.main-content');
    if (!main || !gsap) return;

    const sections = Array.from(main.children).filter((ch) => !ch.classList.contains('welcome-hero'));
    if (sections.length === 0) return;

    gsap.from(sections, {
        opacity: 0,
        y: 22,
        duration: 0.52,
        stagger: 0.07,
        ease: 'power2.out',
        delay: 0.08,
        clearProps: 'opacity,transform',
    });
}

async function mountParticlesInAnchors(THREE) {
    const anchors = document.querySelectorAll('.store-three-anchor');
    if (!anchors.length) return;

    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

    const isDark = document.body.classList.contains('theme-dark');
    const accent = isDark ? 0x38e7c8 : 0x4a9088;
    const accent2 = isDark ? 0x6366f1 : 0x2c5f4f;

    anchors.forEach((anchor) => {
        let w = anchor.clientWidth;
        let h = anchor.clientHeight;
        if (w < 24 || h < 24) {
            w = anchor.offsetWidth;
            h = anchor.offsetHeight;
        }
        if (w < 24 || h < 24) {
            return;
        }
        const small = window.innerWidth < 720;
        const count = saveData() ? 48 : small ? 72 : 130;

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(42, Math.max(w / h, 0.4), 0.1, 120);
        camera.position.z = 28;

        const renderer = new THREE.WebGLRenderer({
            antialias: false,
            alpha: true,
            powerPreference: 'low-power',
        });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2));
        renderer.setSize(w, h, false);
        renderer.setClearColor(0x000000, 0);
        anchor.appendChild(renderer.domElement);

        const geom = new THREE.BufferGeometry();
        const positions = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);

        const c1 = new THREE.Color(accent);
        const c2 = new THREE.Color(accent2);

        for (let i = 0; i < count; i++) {
            const t = i / count;
            const radius = 14 + Math.random() * 16;
            const theta = Math.random() * Math.PI * 2;
            const phi = Math.acos(2 * Math.random() - 1);
            positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
            positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
            positions[i * 3 + 2] = radius * Math.cos(phi);

            const col = c1.clone().lerp(c2, t + Math.random() * 0.35);
            colors[i * 3] = col.r;
            colors[i * 3 + 1] = col.g;
            colors[i * 3 + 2] = col.b;
        }

        geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        const material = new THREE.PointsMaterial({
            size: small ? 0.09 : 0.07,
            vertexColors: true,
            transparent: true,
            opacity: isDark ? 0.42 : 0.38,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            sizeAttenuation: true,
        });

        const points = new THREE.Points(geom, material);
        scene.add(points);

        let raf = 0;
        let alive = true;

        const tick = () => {
            if (!alive) return;
            points.rotation.y += 0.00085;
            points.rotation.x += 0.00035;
            renderer.render(scene, camera);
            raf = requestAnimationFrame(tick);
        };
        tick();

        const ro = new ResizeObserver(() => {
            const nw = anchor.clientWidth;
            const nh = anchor.clientHeight;
            if (nw < 16 || nh < 16) return;
            camera.aspect = nw / nh;
            camera.updateProjectionMatrix();
            renderer.setSize(nw, nh, false);
        });
        ro.observe(anchor);

        window.addEventListener(
            'pagehide',
            () => {
                alive = false;
                cancelAnimationFrame(raf);
                ro.disconnect();
                geom.dispose();
                material.dispose();
                renderer.dispose();
                if (renderer.domElement.parentNode === anchor) {
                    anchor.removeChild(renderer.domElement);
                }
            },
            { once: true },
        );
    });
}

/** مسارات تفعيل طبقة الجسيمات (صفحة تلو الأخرى حسب الخطة). */
function shouldMountThreeParticles(path) {
    if (path === '/' || path === '/home') return true;
    return /^\/compartment\/\d+$/.test(path);
}

async function maybeThree() {
    if (prefersReducedMotion() || saveData()) return;

    const path = storePathKey();
    if (!shouldMountThreeParticles(path)) return;

    /* الدولاب على الموبايل: بدون طبقة جزيئات */
    if (
        path === '/home' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(max-width: 768px)').matches
    ) {
        return;
    }

    if (!document.querySelector('.store-three-anchor')) return;

    try {
        const THREE = await loadThree();
        await mountParticlesInAnchors(THREE);
    } catch (e) {
        console.warn('[store-premium-motion] Three.js failed:', e);
    }
}

async function initMotionLayer() {
    if (prefersReducedMotion()) return;

    let gsap = null;
    try {
        gsap = await loadGsap();
    } catch (e) {
        console.warn('[store-premium-motion] GSAP failed, using CSS fallback:', e);
    }

    setupScrollReveal(gsap);

    const path = storePathKey();
    if (path === '/') {
        runStaggerSections(gsap);
    }
}

function boot() {
    document.documentElement.classList.add('store-motion-enhanced');

    if (prefersReducedMotion()) return;

    initMotionLayer();
    maybeThree();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}
