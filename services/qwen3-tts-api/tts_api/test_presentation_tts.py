import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from tts_api import presentation_tts, store

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"


def make_fixture_pptx(path: Path) -> None:
    files = {
        "[Content_Types].xml": f'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="{CT_NS}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>
</Types>''',
        "ppt/presentation.xml": f'''<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}"><p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>''',
        "ppt/_rels/presentation.xml.rels": f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/></Relationships>''',
        "ppt/slides/slide1.xml": f'''<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}" xmlns:r="{R_NS}"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sld>''',
        "ppt/slides/slide2.xml": f'''<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}" xmlns:r="{R_NS}"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sld>''',
        "ppt/slides/_rels/slide1.xml.rels": f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>''',
        "ppt/notesSlides/notesSlide1.xml": f'''<?xml version="1.0" encoding="UTF-8"?>
<p:notes xmlns:p="{P_NS}" xmlns:a="{A_NS}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes Placeholder"/><p:cNvSpPr/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Hello speaker notes.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>''',
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)


class PresentationTtsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = store.API_DATA_DIR
        store.API_DATA_DIR = self.tmp.name
        store.save_models([{"id": "model-1", "name": "Narrator", "status": "ready"}])
        self.pptx = Path(self.tmp.name) / "fixture.pptx"
        make_fixture_pptx(self.pptx)

    def tearDown(self):
        store.API_DATA_DIR = self.old_data
        self.tmp.cleanup()

    def test_extracts_notes_and_preserves_empty_slide(self):
        slides = presentation_tts.inspect_pptx(str(self.pptx))
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0]["text"], "Hello speaker notes.")
        self.assertEqual(slides[1]["text"], "")

    def test_build_output_embeds_audio_and_empty_slide_advance(self):
        job = presentation_tts.create_presentation_job(str(self.pptx), "fixture.pptx", "model-1", "Fixture")
        slide_audio = Path(job["slides"][0]["output_path"])
        slide_audio.write_bytes(b"ID3fake")
        store.update_presentation_slide(job["id"], 0, status="completed", output_path=str(slide_audio), audio_duration_seconds=2.25, quality={"ok": True, "duration_seconds": 2.25})
        out = presentation_tts.build_pptx_output(job["id"])
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            self.assertTrue(any(name.startswith("ppt/media/narration_") and name.endswith(".mp3") for name in names))
            self.assertIn(f'<Types xmlns="{CT_NS}"'.encode("utf-8"), zf.read("[Content_Types].xml"))
            content_types = ET.fromstring(zf.read("[Content_Types].xml"))
            self.assertTrue(any(node.attrib.get("Extension") == "mp3" for node in content_types.findall(f"{{{CT_NS}}}Default")))
            slide1 = ET.fromstring(zf.read("ppt/slides/slide1.xml"))
            slide2 = ET.fromstring(zf.read("ppt/slides/slide2.xml"))
            self.assertEqual(slide1.find(f"{{{P_NS}}}transition").attrib.get("advClick"), "0")
            self.assertEqual(slide2.find(f"{{{P_NS}}}transition").attrib.get("advTm"), "1500")
            rels = ET.fromstring(zf.read("ppt/slides/_rels/slide1.xml.rels"))
            relationships = rels.findall(f"{{{REL_NS}}}Relationship")
            relationship_types = {rel.attrib.get("Type") for rel in relationships}
            self.assertIn(presentation_tts.MEDIA_REL_TYPE, relationship_types)
            self.assertIn(presentation_tts.AUDIO_REL_TYPE, relationship_types)
            self.assertIn(presentation_tts.IMAGE_REL_TYPE, relationship_types)
            audio = slide1.find(f".//{{{P_NS}}}pic/{{{P_NS}}}nvPicPr/{{{P_NS}}}nvPr/{{{A_NS}}}audioFile")
            media = slide1.find(f".//{{{P14_NS}}}media")
            self.assertIsNotNone(audio)
            self.assertIsNotNone(media)
            self.assertNotEqual(audio.attrib.get(f"{{{R_NS}}}link"), media.attrib.get(f"{{{R_NS}}}embed"))
            self.assertEqual(slide1.find(f"{{{P_NS}}}transition").attrib.get("advTm"), "2750")
            media_duration = slide1.find(f".//{{{P_NS}}}cTn[@id='6']")
            self.assertIsNotNone(media_duration)
            self.assertEqual(media_duration.attrib.get("dur"), "2750")
        presentation_tts.validate_pptx(out)

    def test_delete_presentation_job_removes_files(self):
        job = presentation_tts.create_presentation_job(str(self.pptx), "fixture.pptx", "model-1", "Fixture")
        job_dir = Path(store.presentation_dir(job["id"]))
        self.assertTrue(job_dir.exists())
        deleted = store.delete_presentation_job(job["id"])
        self.assertIsNotNone(deleted)
        self.assertFalse(job_dir.exists())


if __name__ == "__main__":
    unittest.main()
