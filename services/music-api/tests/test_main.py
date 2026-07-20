from __future__ import annotations

from io import BytesIO
import unittest

from starlette.datastructures import FormData, UploadFile

from music_api.main import _split_multipart


class MultipartTests(unittest.TestCase):
    def test_split_multipart_keeps_uploads_out_of_json_payload(self) -> None:
        source = UploadFile(filename="source.flac", file=BytesIO(b"fLaC"))
        reference = UploadFile(filename="reference.wav", file=BytesIO(b"RIFF"))
        ignored = UploadFile(filename="other.wav", file=BytesIO(b"RIFF"))
        form = FormData(
            [
                ("profile_id", "levo2-large-amd"),
                ("mode", "stems"),
                ("duration", "10"),
                ("source_audio", source),
                ("reference_audio", reference),
                ("unsupported_upload", ignored),
            ]
        )

        payload, uploads = _split_multipart(form)

        self.assertEqual(payload, {"profile_id": "levo2-large-amd", "mode": "stems", "duration": "10"})
        self.assertEqual(
            [(role, upload.filename) for role, upload in uploads],
            [("source_audio", "source.flac"), ("reference_audio", "reference.wav")],
        )


if __name__ == "__main__":
    unittest.main()
