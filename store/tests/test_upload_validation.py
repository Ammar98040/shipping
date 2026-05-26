"""اختبارات التحقق من صور الدردشة."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from store.upload_validation import validate_chat_image_files


def _png():
    # PNG صغير جداً (1x1)
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )


@override_settings(CHAT_IMAGE_MAX_BYTES=5000, CHAT_IMAGE_MAX_COUNT=3)
class ChatImageValidationTests(SimpleTestCase):
    def test_empty_ok(self):
        ok, err = validate_chat_image_files([])
        self.assertEqual(ok, [])
        self.assertIsNone(err)

    def test_valid_png(self):
        f = SimpleUploadedFile('a.png', _png(), content_type='image/png')
        ok, err = validate_chat_image_files([f])
        self.assertEqual(len(ok), 1)
        self.assertIsNone(err)

    def test_too_many_files(self):
        files = [
            SimpleUploadedFile(f'{i}.png', _png(), content_type='image/png')
            for i in range(4)
        ]
        ok, err = validate_chat_image_files(files)
        self.assertIsNone(ok)
        self.assertEqual(err.get('error'), 'too_many_images')

    def test_bad_extension(self):
        f = SimpleUploadedFile('x.exe', b'abc', content_type='application/octet-stream')
        ok, err = validate_chat_image_files([f])
        self.assertIsNone(ok)
        self.assertEqual(err.get('error'), 'image_invalid_type')

    def test_oversize(self):
        big = BytesIO(b'x' * 6000)
        f = SimpleUploadedFile('big.png', big.read(), content_type='image/png')
        ok, err = validate_chat_image_files([f])
        self.assertIsNone(ok)
        self.assertEqual(err.get('error'), 'image_too_large')
