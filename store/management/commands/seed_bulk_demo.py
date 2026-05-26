"""
زرع بيانات تجريبية كبيرة للتطوير والاختبار:
50 خانة، 200 رف، 400 صنف، 1000 منتج (كل منتج بنسخة واحدة على الأقل)،
60 عميل مسجل، 20 موظف مستودع، 20 مندوب شحن، 10 خدمة عملاء، 5 مسؤولين لوحة الإدارة.

إزالة ما زُرع سابقاً: python manage.py seed_bulk_demo --clear
"""
import sys
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import (
    Category,
    Compartment,
    Product,
    ProductVariant,
    Shelf,
    UserProfile,
)

User = get_user_model()

# بادئات ثابتة لتمييز ما زُرع بهذا الأمر (للحذف الآمن بـ --clear)
CATALOG_NAME_PREFIX = "تجريبي بلك"
USER_PREFIX_CUST = "demoshop_cust_"
USER_PREFIX_WH = "demoshop_wh_"
USER_PREFIX_SHIP = "demoshop_ship_"
USER_PREFIX_CS = "demoshop_cs_"
USER_PREFIX_ADMIN = "demoshop_admin_"
PRODUCT_SKU_PREFIX = "SEED-"

DEFAULT_PASSWORD = "DemoSeed2026!"

N_COMPARTMENTS = 50
N_SHELVES = 200
N_CATEGORIES = 400
N_PRODUCTS = 1000
N_CUSTOMERS = 60
N_PACKERS = 20
N_COURIERS = 20
N_CUSTOMER_SERVICE = 10
N_ADMINS = 5


def _utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError, AttributeError):
            pass


class Command(BaseCommand):
    # نص help بالإنجليزي لتفادي UnicodeEncodeError عند `manage.py help` على Windows (cp1252)
    help = (
        "Seed bulk demo data: 50 compartments, 200 shelves, 400 categories, 1000 products+variants; "
        f"{N_CUSTOMERS} customers, {N_PACKERS} warehouse packers, {N_COURIERS} couriers, "
        f"{N_CUSTOMER_SERVICE} customer-service staff, {N_ADMINS} manage admins. "
        f"Default password for all seeded accounts: {DEFAULT_PASSWORD}. "
        "Use --clear to remove seeded catalog and demoshop_* users. "
        "With SQLite, stop runserver while seeding to avoid DB locks."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove seeded catalog (bulk prefix) and all demoshop_* users, then exit.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Resume partial seed or allow one-sided seed; see command logic.",
        )

    def handle(self, *args, **options):
        _utf8_stdout()  # رسائل عربية في المخرجات
        if options["clear"]:
            self._clear_seed()
            self.stdout.write(self.style.SUCCESS("تم مسح بيانات الزرع التجريبي."))
            return

        has_users = User.objects.filter(username__startswith="demoshop_").exists()
        has_catalog = Compartment.objects.filter(
            name_ar__startswith=CATALOG_NAME_PREFIX
        ).exists()

        if options["force"]:
            if has_catalog and has_users:
                self.stdout.write(
                    self.style.ERROR(
                        "يوجد زرع كامل مسبقاً. للاستبدال شغّل أولاً: python manage.py seed_bulk_demo --clear"
                    )
                )
                return
            if has_catalog and not has_users:
                self.stdout.write(
                    self.style.NOTICE("متابعة: إنشاء حسابات demoshop_* فقط (الكتالوج التجريبي موجود).")
                )
                with transaction.atomic():
                    self._seed_users()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"اكتمل زرع المستخدمين. كلمة المرور: {DEFAULT_PASSWORD}"
                    )
                )
                return
            if has_users and not has_catalog:
                self.stdout.write(
                    self.style.NOTICE("متابعة: إنشاء الكتالوج التجريبي فقط (حسابات demoshop_* موجودة).")
                )
                with transaction.atomic():
                    self._seed_catalog()
                self.stdout.write(self.style.SUCCESS("اكتمل زرع الكتالوج."))
                return
        elif has_users or has_catalog:
            if has_catalog and not has_users:
                self.stdout.write(
                    self.style.WARNING(
                        "الكتالوج التجريبي موجود دون حسابات demoshop_*. أكمل بـ: "
                        "python manage.py seed_bulk_demo --force"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "يوجد زرع سابق. للاستبدال: python manage.py seed_bulk_demo --clear ثم أعد الأمر بدون --force. "
                        "مع SQLite يُفضّل إيقاف runserver مؤقتاً لتفادي قفل قاعدة البيانات."
                    )
                )
            return

        # معاملة منفصلة للكتالوج ثم للمستخدمين حتى لا يُفقد الكتالوج إن فشل جزء الحسابات
        with transaction.atomic():
            self._seed_catalog()
        with transaction.atomic():
            self._seed_users()

        self.stdout.write(
            self.style.SUCCESS(
                f"اكتمل الزرع. كلمة مرور جميع الحسابات التجريبية: {DEFAULT_PASSWORD}"
            )
        )

    def _clear_seed(self):
        with transaction.atomic():
            deleted_c, _ = Compartment.objects.filter(
                name_ar__startswith=CATALOG_NAME_PREFIX
            ).delete()
            deleted_u, _ = User.objects.filter(
                username__startswith="demoshop_"
            ).delete()
        self.stdout.write(f"  حُذف من الكتالوج (سجلات متتالية): {deleted_c}")
        self.stdout.write(f"  حُذف من المستخدمين: {deleted_u}")

    def _seed_catalog(self):
        compartments = [
            Compartment(
                name_ar=f"{CATALOG_NAME_PREFIX} — خانة {i + 1:02d}",
                name_en=f"bulk-comp-{i + 1:02d}",
                order=i,
                is_active=True,
            )
            for i in range(N_COMPARTMENTS)
        ]
        Compartment.objects.bulk_create(compartments)

        comps = list(
            Compartment.objects.filter(name_ar__startswith=CATALOG_NAME_PREFIX).order_by(
                "order", "id"
            )[:N_COMPARTMENTS]
        )
        if len(comps) != N_COMPARTMENTS:
            raise RuntimeError(f"توقع {N_COMPARTMENTS} خانة بعد الإنشاء، وُجد {len(comps)}")

        shelves = []
        for comp in comps:
            for j in range(N_SHELVES // N_COMPARTMENTS):
                shelves.append(
                    Shelf(
                        compartment=comp,
                        name_ar=f"{CATALOG_NAME_PREFIX} — رف {comp.order + 1:02d}-{j + 1}",
                        name_en=f"bulk-shelf-{comp.order + 1:02d}-{j + 1}",
                        order=j,
                        is_active=True,
                    )
                )
        Shelf.objects.bulk_create(shelves)

        sh_list = list(
            Shelf.objects.filter(name_ar__startswith=CATALOG_NAME_PREFIX).order_by(
                "compartment_id", "order", "id"
            )[:N_SHELVES]
        )
        if len(sh_list) != N_SHELVES:
            raise RuntimeError(f"توقع {N_SHELVES} رفاً، وُجد {len(sh_list)}")

        categories = []
        for shelf in sh_list:
            for k in range(N_CATEGORIES // N_SHELVES):
                categories.append(
                    Category(
                        shelf=shelf,
                        name_ar=f"{CATALOG_NAME_PREFIX} — صنف {shelf.id}-{k + 1}",
                        name_en=f"bulk-cat-{shelf.id}-{k + 1}",
                        order=k,
                        is_active=True,
                    )
                )
        Category.objects.bulk_create(categories)

        cats = list(
            Category.objects.filter(name_ar__startswith=CATALOG_NAME_PREFIX).order_by(
                "shelf_id", "order", "id"
            )[:N_CATEGORIES]
        )
        if len(cats) != N_CATEGORIES:
            raise RuntimeError(f"توقع {N_CATEGORIES} صنفاً، وُجد {len(cats)}")

        products = []
        p_idx = 0
        for ci, cat in enumerate(cats):
            n_here = 3 if ci < (N_PRODUCTS - 2 * N_CATEGORIES) else 2
            for _ in range(n_here):
                p_idx += 1
                products.append(
                    Product(
                        category=cat,
                        sku=f"{PRODUCT_SKU_PREFIX}{p_idx:05d}",
                        slug=f"seed-prod-{p_idx:05d}",
                        name_ar=f"{CATALOG_NAME_PREFIX} — منتج {p_idx:04d}",
                        name_en=f"bulk-product-{p_idx:05d}",
                        description_ar="وصف تجريبي للمنتج.",
                        description_en="Demo product description.",
                        price=Decimal("49.00") + Decimal(p_idx % 250),
                        stock=0,
                        order=(p_idx - 1) % 500,
                        is_active=True,
                    )
                )
                if p_idx >= N_PRODUCTS:
                    break
            if p_idx >= N_PRODUCTS:
                break

        if len(products) != N_PRODUCTS:
            raise RuntimeError(f"منطق الزرع: تُوقع {N_PRODUCTS} منتجاً، وُجد {len(products)}")

        Product.objects.bulk_create(products, batch_size=500)

        prods = list(
            Product.objects.filter(sku__startswith=PRODUCT_SKU_PREFIX).order_by("sku")[
                :N_PRODUCTS
            ]
        )
        if len(prods) != N_PRODUCTS:
            raise RuntimeError(f"توقع {N_PRODUCTS} منتجاً، وُجد {len(prods)}")

        variants = []
        variant_stocks = []
        colors = [
            ("أحمر", "#CC3333"),
            ("أزرق", "#3366CC"),
            ("أخضر", "#33AA66"),
            ("أسود", "#222222"),
            ("بيج", "#C4A574"),
        ]
        for i, prod in enumerate(prods):
            cname, chex = colors[i % len(colors)]
            stock_q = 15 + (i % 80)
            variant_stocks.append(stock_q)
            variants.append(
                ProductVariant(
                    product=prod,
                    code=f"{prod.sku}-V1",
                    title="",
                    color_name=cname,
                    color_hex=chex,
                    price=None,
                    stock_quantity=stock_q,
                    sort_order=0,
                    is_active=True,
                )
            )
        ProductVariant.objects.bulk_create(variants, batch_size=500)

        # مزامنة حقل stock في المنتج مع مخزون النسخة (للواجهات التي تعتمد عليه)
        for prod, sq in zip(prods, variant_stocks):
            prod.stock = sq
        Product.objects.bulk_update(prods, ["stock"], batch_size=500)

        self.stdout.write(
            self.style.NOTICE(
                f"كتالوج: {N_COMPARTMENTS} خانة، {N_SHELVES} رف، {N_CATEGORIES} صنف، "
                f"{N_PRODUCTS} منتج، {N_PRODUCTS} نسخة."
            )
        )

    def _seed_users(self):
        # تجزئة كلمة المرور مرة واحدة + bulk_create لتسريع التشغيل وتقليل قفل SQLite
        hashed = make_password(DEFAULT_PASSWORD)
        users = []
        profiles = []

        def add_batch(username, email, *, is_staff=False, is_superuser=False, acc_type=None, phone="", avail=None):
            users.append(
                User(
                    username=username,
                    email=email,
                    password=hashed,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                    is_active=True,
                )
            )
            kw = {"account_type": acc_type or UserProfile.ACCOUNT_REGULAR, "phone": phone}
            if avail is not None:
                kw["is_available"] = avail
            profiles.append((len(users) - 1, kw))

        for i in range(1, N_CUSTOMERS + 1):
            add_batch(
                f"{USER_PREFIX_CUST}{i:03d}",
                f"{USER_PREFIX_CUST}{i:03d}@example.invalid",
                acc_type=UserProfile.ACCOUNT_REGULAR,
                phone=f"050000{i:04d}",
            )

        for i in range(1, N_PACKERS + 1):
            add_batch(
                f"{USER_PREFIX_WH}{i:03d}",
                f"{USER_PREFIX_WH}{i:03d}@example.invalid",
                acc_type=UserProfile.ACCOUNT_PACKER,
                phone=f"051000{i:04d}",
                avail=True,
            )

        for i in range(1, N_COURIERS + 1):
            add_batch(
                f"{USER_PREFIX_SHIP}{i:03d}",
                f"{USER_PREFIX_SHIP}{i:03d}@example.invalid",
                acc_type=UserProfile.ACCOUNT_COURIER,
                phone=f"052000{i:04d}",
                avail=True,
            )

        for i in range(1, N_CUSTOMER_SERVICE + 1):
            add_batch(
                f"{USER_PREFIX_CS}{i:03d}",
                f"{USER_PREFIX_CS}{i:03d}@example.invalid",
                is_staff=True,
                acc_type=UserProfile.ACCOUNT_CUSTOMER_SERVICE,
                phone=f"053000{i:04d}",
            )

        for i in range(1, N_ADMINS + 1):
            add_batch(
                f"{USER_PREFIX_ADMIN}{i:03d}",
                f"{USER_PREFIX_ADMIN}{i:03d}@example.invalid",
                is_staff=True,
                acc_type=UserProfile.ACCOUNT_REGULAR,
                phone=f"054000{i:04d}",
            )

        User.objects.bulk_create(users, batch_size=200)

        prof_objs = []
        for u_idx, pdata in profiles:
            u = users[u_idx]
            prof_objs.append(UserProfile(user=u, **pdata))
        UserProfile.objects.bulk_create(prof_objs, batch_size=200)

        self.stdout.write(
            self.style.NOTICE(
                f"مستخدمون: {N_CUSTOMERS} عميل، {N_PACKERS} مستودع، {N_COURIERS} شحن، "
                f"{N_CUSTOMER_SERVICE} خدمة عملاء، {N_ADMINS} مسؤول."
            )
        )
