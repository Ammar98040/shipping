from decimal import Decimal

from store.models import Category, Product


def run() -> tuple[int, int]:
    created = 0
    extra_per_category = 8

    categories = Category.objects.filter(is_active=True).order_by("id")
    for category in categories:
        initial_count = Product.objects.filter(category=category).count()
        target_total = initial_count + extra_per_category
        idx = 1

        while Product.objects.filter(category=category).count() < target_total:
            name_ar = f"{category.name_ar} إضافي {idx}"
            exists = Product.objects.filter(category=category, name_ar=name_ar).exists()
            if exists:
                idx += 1
                continue

            price = Decimal(49 + ((category.id * 17 + idx * 13) % 351))
            stock = 5 + ((category.id * 11 + idx * 7) % 46)

            Product.objects.create(
                category=category,
                name_ar=name_ar,
                name_en=f"Extra {category.name_en or category.name_ar} {idx}",
                description_ar=f"منتج إضافي ضمن {category.name_ar}.",
                description_en=f"Extra product in {category.name_en or category.name_ar}.",
                price=price,
                stock=stock,
                order=initial_count + idx,
                is_active=True,
            )
            created += 1
            idx += 1

    return created, Product.objects.count()


if __name__ == "__main__":
    created_count, total_count = run()
    print(f"EXTRA_PRODUCTS_CREATED={created_count}")
    print(f"TOTAL_PRODUCTS={total_count}")
