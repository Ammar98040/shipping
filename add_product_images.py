"""
Add demo images to products
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from store.models import Product

# Available images
images = [
    'products/product-1.svg',
    'products/product-2.svg',
    'products/product-3.svg',
    'products/product-4.svg',
    'products/product-5.svg',
    'products/product-6.svg',
]

# Get all products
products = Product.objects.all()
print(f'Total products: {products.count()}')

# Add image to each product
updated_count = 0
for index, product in enumerate(products):
    if not product.image:
        # Select image by rotating through list
        image_path = images[index % len(images)]
        product.image = image_path
        product.save()
        updated_count += 1
        print(f'Updated product {product.id} - {image_path}')

print(f'\nUpdated {updated_count} products with demo images')
