from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.datastructures import MultiValueDict
from django.test import SimpleTestCase
from unittest.mock import patch
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from market.forms import ProductImageForm

class ImageReencodingTests(SimpleTestCase):
    def upload(self,fmt,mime,name):
        data=BytesIO(); mode="RGBA" if fmt == "PNG" else "RGB"; Image.new(mode,(8,8),(255,0,0,128) if mode=="RGBA" else "red").save(data,fmt)
        return SimpleUploadedFile(name,data.getvalue(),content_type=mime)
    def test_jpeg_png_and_webp_are_reencoded_with_matching_format(self):
        for fmt,mime,name in (("JPEG","image/jpeg","x.jpg"),("PNG","image/png","x.png"),("WEBP","image/webp","x.webp")):
            form=ProductImageForm({}, MultiValueDict({"images":[self.upload(fmt,mime,name)]})); self.assertTrue(form.is_valid(),form.errors)
            stored=form.cleaned_data["images"][0]; image=Image.open(stored)
            self.assertEqual(image.format,fmt); self.assertTrue(stored.name.endswith({"JPEG":".jpg","PNG":".png","WEBP":".webp"}[fmt]))
    def test_extension_and_mime_spoof_are_rejected(self):
        form=ProductImageForm({}, MultiValueDict({"images":[self.upload("PNG","image/jpeg","evil.jpg")]})); self.assertFalse(form.is_valid())
    def test_jpeg_exif_and_png_metadata_are_removed_while_alpha_is_preserved(self):
        jpeg=BytesIO(); exif=Image.Exif(); exif[270]="private location"; Image.new("RGB",(8,8),"red").save(jpeg,"JPEG",exif=exif)
        form=ProductImageForm({},MultiValueDict({"images":[SimpleUploadedFile("photo.jpg",jpeg.getvalue(),content_type="image/jpeg")]})); self.assertTrue(form.is_valid(),form.errors)
        self.assertFalse(Image.open(form.cleaned_data["images"][0]).getexif())
        png=BytesIO(); info=PngInfo(); info.add_text("comment","private"); Image.new("RGBA",(8,8),(1,2,3,80)).save(png,"PNG",pnginfo=info)
        form=ProductImageForm({},MultiValueDict({"images":[SimpleUploadedFile("alpha.png",png.getvalue(),content_type="image/png")]})); self.assertTrue(form.is_valid(),form.errors)
        cleaned=Image.open(form.cleaned_data["images"][0]); self.assertEqual(cleaned.mode,"RGBA"); self.assertNotIn("comment",cleaned.info)
    def test_corrupt_and_oversize_dimensions_are_rejected(self):
        corrupt=ProductImageForm({},MultiValueDict({"images":[SimpleUploadedFile("bad.png",b"not an image",content_type="image/png")]})); self.assertFalse(corrupt.is_valid())
        huge=BytesIO(); Image.new("RGB",(4097,1),"red").save(huge,"PNG")
        form=ProductImageForm({},MultiValueDict({"images":[SimpleUploadedFile("large.png",huge.getvalue(),content_type="image/png")]})); self.assertFalse(form.is_valid())
    def test_decompression_bomb_warning_is_an_upload_error(self):
        image=BytesIO(); Image.new("RGB",(2,2),"red").save(image,"PNG")
        with patch.object(Image,"MAX_IMAGE_PIXELS",1):
            form=ProductImageForm({},MultiValueDict({"images":[SimpleUploadedFile("bomb.png",image.getvalue(),content_type="image/png")]}))
            self.assertFalse(form.is_valid())
