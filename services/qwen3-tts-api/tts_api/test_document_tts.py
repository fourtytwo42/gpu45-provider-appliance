import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from tts_api import document_tts, store


def make_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("fixture-book")
    book.set_title("Fixture Book Volume 2")
    book.set_language("en")
    toc = epub.EpubHtml(title="Table of Contents", file_name="toc.xhtml", lang="en")
    toc.content = """<html><body><h1>Table of Contents</h1><p>Prologue</p><p>Chapter 1</p><p>Chapter 2</p></body></html>"""
    prologue = epub.EpubHtml(title="Prologue", file_name="prologue.xhtml", lang="en")
    prologue.content = """<html><body><h1>Prologue</h1><p>This is the first real narrative sentence.</p></body></html>"""
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter1.xhtml", lang="en")
    chapter.content = """<html><body><h1>Chapter 1</h1><p>The story continues here.</p></body></html>"""
    book.add_item(toc)
    book.add_item(prologue)
    book.add_item(chapter)
    book.toc = (
        epub.Link("prologue.xhtml", "Prologue", "prologue"),
        epub.Link("chapter1.xhtml", "Chapter 1", "chapter1"),
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", toc, prologue, chapter]
    epub.write_epub(str(path), book)


class DocumentTtsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = store.API_DATA_DIR
        store.API_DATA_DIR = self.tmp.name
        store.save_models([{"id": "model-1", "name": "Narrator", "status": "ready"}])

    def tearDown(self):
        store.API_DATA_DIR = self.old_data
        self.tmp.cleanup()

    def test_epub_extraction_skips_toc_and_starts_at_prologue(self):
        path = Path(self.tmp.name) / "book.epub"
        make_epub(path)
        text = document_tts.extract_text(str(path), "Fixture Book Volume 2.epub")
        self.assertTrue(text.startswith("Prologue"), text[:120])
        self.assertIn("first real narrative", text)
        self.assertNotIn("Table of Contents", text)

    def test_audiobook_job_prepends_intro_and_sets_one_second_pause(self):
        path = Path(self.tmp.name) / "book.epub"
        make_epub(path)
        job = document_tts.create_audiobook_job(str(path), "Fixture Book Volume 2.epub", "model-1", None)
        self.assertEqual(job["chunks"][0]["role"], "intro")
        self.assertEqual(job["chunks"][0]["pause_after_ms"], 1000)
        self.assertEqual(job["chunks"][0]["text"], "Fixture Book. Volume 2.")
        self.assertEqual(job["chunks"][1]["role"], "content")
        self.assertTrue(job["chunks"][1]["text"].startswith("Prologue"), job["chunks"][1]["text"])
        self.assertEqual(job["front_matter_policy"], "skip_index_start_at_first_section")

    def test_embedded_text_toc_strips_to_repeated_prologue(self):
        text = """Prologue Chapter 1: Is This Another World? Chapter 2: The Creeped-Out Maid Chapter 3: A Textbook of Magic Chapter 4: Master Chapter 5: Swords and Sorcery Chapter 6: Reasons for Respect Chapter 7: Friends Chapter 8: Obliviousness Chapter 9: Emergency Family Meeting Chapter 10: Stunted Growth Chapter 11: Parted Extra Chapter: The Mother of the Greyrat Family Character Design Concept Gallery Newsletter Download all your Fav Light Novels from Just Light Novels Prologue I was a thirty-four-year-old man with no job and nowhere to live."""
        stripped = document_tts._strip_leading_front_matter(text)
        self.assertTrue(stripped.startswith("Prologue I was"), stripped[:160])
        self.assertNotIn("Chapter 11: Parted", stripped[:300])
        self.assertNotIn("Just Light Novels", stripped[:100])

    def test_regenerate_completed_chunk_removes_audio_and_queues_next(self):
        path = Path(self.tmp.name) / "book.epub"
        make_epub(path)
        job = document_tts.create_audiobook_job(str(path), "Fixture Book Volume 2.epub", "model-1", None)
        chunk_path = Path(job["chunks"][1]["output_path"])
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_bytes(b"old audio")
        stitched_path = Path(job["stitched_output_path"])
        stitched_path.write_bytes(b"stitched")
        store.update_audiobook_chunk(job["id"], 1, status="completed", output_bytes=9, quality={"ok": True}, updated_at=document_tts.utcnow())
        updated = document_tts.regenerate_audiobook_chunk(job["id"], 1)
        chunk = next(c for c in updated["chunks"] if c["index"] == 1)
        self.assertEqual(updated["status"], "queued")
        self.assertEqual(updated["regenerate_queue"], [1])
        self.assertEqual(chunk["status"], "pending")
        self.assertFalse(chunk_path.exists())
        self.assertFalse(stitched_path.exists())
        self.assertEqual(updated["completed_chunks"], 0)

    def test_regenerate_rejects_skipped_front_matter(self):
        path = Path(self.tmp.name) / "book.epub"
        make_epub(path)
        job = document_tts.create_audiobook_job(str(path), "Fixture Book Volume 2.epub", "model-1", None)
        store.update_audiobook_chunk(job["id"], 1, status="skipped", role="skipped_front_matter", updated_at=document_tts.utcnow())
        with self.assertRaises(ValueError):
            document_tts.regenerate_audiobook_chunk(job["id"], 1)

    def test_regenerate_running_chunk_keeps_current_and_queues_next(self):
        path = Path(self.tmp.name) / "book.epub"
        make_epub(path)
        job = document_tts.create_audiobook_job(str(path), "Fixture Book Volume 2.epub", "model-1", None)
        store.update_audiobook_job(job["id"], status="running")
        store.update_audiobook_chunk(job["id"], 1, status="running", updated_at=document_tts.utcnow())
        updated = document_tts.regenerate_audiobook_chunk(job["id"], 1)
        chunk = next(c for c in updated["chunks"] if c["index"] == 1)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["regenerate_queue"], [1])
        self.assertEqual(chunk["status"], "running")
        self.assertTrue(chunk["regenerate_requested"])


if __name__ == "__main__":
    unittest.main()