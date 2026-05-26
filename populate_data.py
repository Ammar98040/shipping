"""
Script to populate the database with sample data
"""
import os
import sys
import django
from pathlib import Path

# Set console encoding to UTF-8 for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from store.models import Compartment, Shelf, Category, Product
from django.core.files import File

print("Starting data population...")

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / 'images'
ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def load_image_paths():
    if not IMAGES_DIR.exists():
        print(f"Images folder not found: {IMAGES_DIR}")
        return []

    image_paths = [
        p for p in IMAGES_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS
    ]
    image_paths.sort(key=lambda p: p.name.lower())
    print(f"Found {len(image_paths)} image(s) in images folder.")
    return image_paths


class ImageDistributor:
    def __init__(self, image_paths):
        self.image_paths = image_paths
        self.index = 0

    def next(self):
        if not self.image_paths:
            return None
        image_path = self.image_paths[self.index % len(self.image_paths)]
        self.index += 1
        return image_path


def assign_image(instance, field_name, image_path):
    if not image_path:
        return False
    with image_path.open('rb') as fh:
        getattr(instance, field_name).save(image_path.name, File(fh), save=False)
    return True


image_pool = load_image_paths()
distributor = ImageDistributor(image_pool)

# 1. Create Compartments
print("\n1. Creating compartments...")
compartments_data = [
    {'name_ar': 'الملابس', 'order': 1},
    {'name_ar': 'الشنط', 'order': 2},
    {'name_ar': 'الأحذية', 'order': 3},
    {'name_ar': 'الإكسسوارات', 'order': 4},
]

compartments = {}
for data in compartments_data:
    comp, created = Compartment.objects.get_or_create(
        name_ar=data['name_ar'],
        defaults={'order': data['order'], 'is_active': True}
    )
    if assign_image(comp, 'image', distributor.next()):
        comp.save(update_fields=['image'])
    compartments[data['name_ar']] = comp
    status = "Created" if created else "Already exists"
    print(f"  - {data['name_ar']}: {status}")

# 2. Create Shelves
print("\n2. Creating shelves...")
shelves_data = [
    # ملابس
    {'compartment': 'الملابس', 'name_ar': 'صيفي', 'order': 1},
    {'compartment': 'الملابس', 'name_ar': 'شتوي', 'order': 2},
    {'compartment': 'الملابس', 'name_ar': 'رياضي', 'order': 3},
    {'compartment': 'الملابس', 'name_ar': 'رسمي', 'order': 4},
    # شنط
    {'compartment': 'الشنط', 'name_ar': 'يومية', 'order': 1},
    {'compartment': 'الشنط', 'name_ar': 'رسمية', 'order': 2},
    {'compartment': 'الشنط', 'name_ar': 'مدرسية', 'order': 3},
    # أحذية
    {'compartment': 'الأحذية', 'name_ar': 'كاجوال', 'order': 1},
    {'compartment': 'الأحذية', 'name_ar': 'رياضية', 'order': 2},
    {'compartment': 'الأحذية', 'name_ar': 'رسمية', 'order': 3},
    # إكسسوارات
    {'compartment': 'الإكسسوارات', 'name_ar': 'ساعات', 'order': 1},
    {'compartment': 'الإكسسوارات', 'name_ar': 'نظارات', 'order': 2},
    {'compartment': 'الإكسسوارات', 'name_ar': 'أحزمة', 'order': 3},
]

shelves = {}
for data in shelves_data:
    comp = compartments[data['compartment']]
    shelf, created = Shelf.objects.get_or_create(
        compartment=comp,
        name_ar=data['name_ar'],
        defaults={'order': data['order'], 'is_active': True}
    )
    if assign_image(shelf, 'image', distributor.next()):
        shelf.save(update_fields=['image'])
    shelves[f"{data['compartment']}-{data['name_ar']}"] = shelf
    status = "Created" if created else "Already exists"
    print(f"  - {data['compartment']} > {data['name_ar']}: {status}")

# 3. Create Categories
print("\n3. Creating categories...")
categories_data = [
    # صيفي
    {'shelf': 'الملابس-صيفي', 'name_ar': 'تيشيرتات', 'order': 1},
    {'shelf': 'الملابس-صيفي', 'name_ar': 'شورتات', 'order': 2},
    {'shelf': 'الملابس-صيفي', 'name_ar': 'فساتين صيفية', 'order': 3},
    # شتوي
    {'shelf': 'الملابس-شتوي', 'name_ar': 'جاكيتات', 'order': 1},
    {'shelf': 'الملابس-شتوي', 'name_ar': 'سترات', 'order': 2},
    {'shelf': 'الملابس-شتوي', 'name_ar': 'بناطيل', 'order': 3},
    # رياضي
    {'shelf': 'الملابس-رياضي', 'name_ar': 'تيشيرتات رياضية', 'order': 1},
    {'shelf': 'الملابس-رياضي', 'name_ar': 'بناطيل رياضية', 'order': 2},
    {'shelf': 'الملابس-رياضي', 'name_ar': 'طقم رياضي', 'order': 3},
    # رسمي
    {'shelf': 'الملابس-رسمي', 'name_ar': 'قمصان', 'order': 1},
    {'shelf': 'الملابس-رسمي', 'name_ar': 'بدل', 'order': 2},
    {'shelf': 'الملابس-رسمي', 'name_ar': 'بلايز رسمية', 'order': 3},
    # شنط يومية
    {'shelf': 'الشنط-يومية', 'name_ar': 'شنط كروس', 'order': 1},
    {'shelf': 'الشنط-يومية', 'name_ar': 'حقائب يد', 'order': 2},
    # شنط رسمية
    {'shelf': 'الشنط-رسمية', 'name_ar': 'حقائب عمل', 'order': 1},
    {'shelf': 'الشنط-رسمية', 'name_ar': 'محافظ', 'order': 2},
    # شنط مدرسية
    {'shelf': 'الشنط-مدرسية', 'name_ar': 'شنط ظهر', 'order': 1},
    {'shelf': 'الشنط-مدرسية', 'name_ar': 'حقائب كتب', 'order': 2},
    # أحذية كاجوال
    {'shelf': 'الأحذية-كاجوال', 'name_ar': 'أحذية قماش', 'order': 1},
    {'shelf': 'الأحذية-كاجوال', 'name_ar': 'صنادل', 'order': 2},
    # أحذية رياضية
    {'shelf': 'الأحذية-رياضية', 'name_ar': 'أحذية جري', 'order': 1},
    {'shelf': 'الأحذية-رياضية', 'name_ar': 'أحذية تدريب', 'order': 2},
    # أحذية رسمية
    {'shelf': 'الأحذية-رسمية', 'name_ar': 'أحذية جلد', 'order': 1},
    {'shelf': 'الأحذية-رسمية', 'name_ar': 'كعب عالي', 'order': 2},
    # ساعات
    {'shelf': 'الإكسسوارات-ساعات', 'name_ar': 'ساعات يد رجالية', 'order': 1},
    {'shelf': 'الإكسسوارات-ساعات', 'name_ar': 'ساعات يد نسائية', 'order': 2},
    # نظارات
    {'shelf': 'الإكسسوارات-نظارات', 'name_ar': 'نظارات شمسية', 'order': 1},
    {'shelf': 'الإكسسوارات-نظارات', 'name_ar': 'نظارات طبية', 'order': 2},
    # أحزمة
    {'shelf': 'الإكسسوارات-أحزمة', 'name_ar': 'أحزمة جلد', 'order': 1},
]

categories = {}
for data in categories_data:
    shelf = shelves[data['shelf']]
    cat, created = Category.objects.get_or_create(
        shelf=shelf,
        name_ar=data['name_ar'],
        defaults={'order': data['order'], 'is_active': True}
    )
    if assign_image(cat, 'image', distributor.next()):
        cat.save(update_fields=['image'])
    categories[f"{data['shelf']}-{data['name_ar']}"] = cat
    status = "Created" if created else "Already exists"
    print(f"  - {data['name_ar']}: {status}")

# 4. Create Products
print("\n4. Creating products...")
products_created = 0
products_updated = 0

# قاموس الأسعار والمخزون لكل فئة
product_templates = {
    'تيشيرتات': {'base_price': 50, 'count': 8},
    'شورتات': {'base_price': 80, 'count': 6},
    'فساتين صيفية': {'base_price': 150, 'count': 5},
    'جاكيتات': {'base_price': 200, 'count': 6},
    'سترات': {'base_price': 120, 'count': 5},
    'بناطيل': {'base_price': 100, 'count': 7},
    'تيشيرتات رياضية': {'base_price': 60, 'count': 6},
    'بناطيل رياضية': {'base_price': 90, 'count': 5},
    'طقم رياضي': {'base_price': 180, 'count': 4},
    'قمصان': {'base_price': 100, 'count': 6},
    'بدل': {'base_price': 500, 'count': 4},
    'بلايز رسمية': {'base_price': 80, 'count': 5},
    'شنط كروس': {'base_price': 120, 'count': 5},
    'حقائب يد': {'base_price': 150, 'count': 6},
    'حقائب عمل': {'base_price': 250, 'count': 4},
    'محافظ': {'base_price': 180, 'count': 5},
    'شنط ظهر': {'base_price': 140, 'count': 7},
    'حقائب كتب': {'base_price': 100, 'count': 5},
    'أحذية قماش': {'base_price': 100, 'count': 6},
    'صنادل': {'base_price': 80, 'count': 5},
    'أحذية جري': {'base_price': 200, 'count': 6},
    'أحذية تدريب': {'base_price': 180, 'count': 5},
    'أحذية جلد': {'base_price': 300, 'count': 4},
    'كعب عالي': {'base_price': 250, 'count': 5},
    'ساعات يد رجالية': {'base_price': 500, 'count': 4},
    'ساعات يد نسائية': {'base_price': 450, 'count': 4},
    'نظارات شمسية': {'base_price': 150, 'count': 6},
    'نظارات طبية': {'base_price': 200, 'count': 5},
    'أحزمة جلد': {'base_price': 80, 'count': 5},
}

for cat_key, category in categories.items():
    cat_name = category.name_ar
    if cat_name in product_templates:
        template = product_templates[cat_name]
        base_price = template['base_price']
        count = template['count']
        
        for i in range(1, count + 1):
            name = f"{cat_name} - موديل {i}"
            price = base_price + (i * 10)
            stock = 15 + (i * 5)
            
            product, created = Product.objects.get_or_create(
                category=category,
                name_ar=name,
                defaults={
                    'price': price,
                    'stock': stock,
                    'order': i,
                    'is_active': True
                }
            )

            # تحديث المنتجات الموجودة + إضافة الصور للجميع
            if not created:
                product.stock = stock
                assign_image(product, 'image', distributor.next())
                product.save(update_fields=['stock', 'image'])
                products_updated += 1
            else:
                assign_image(product, 'image', distributor.next())
                product.save(update_fields=['image'])
                products_created += 1

print(f"\nProducts created: {products_created}")
print(f"Products updated: {products_updated}")
print(f"Total products: {Product.objects.count()}")

print("\n" + "="*50)
print("Data population completed successfully!")
print("="*50)
