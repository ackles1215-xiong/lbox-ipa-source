import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.update_sources import UpdateSkipped, matching_ipa, read_ipa_metadata


class UpdateSourceTests(unittest.TestCase):
    def test_release_without_ipa_is_skipped(self):
        release = {"tag_name": "v9.9.9", "assets": [{"name": "symbols.zip"}]}
        with self.assertRaises(UpdateSkipped):
            matching_ipa(release, r"(?i)^App.*\.ipa$")

    def test_reads_metadata_without_extracting_ipa(self):
        plist = {
            "CFBundleIdentifier": "com.example.App",
            "CFBundleShortVersionString": "1.2.3",
            "CFBundleVersion": "45",
            "MinimumOSVersion": "16.0",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "App.ipa"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Payload/App.app/Info.plist", json_to_plist(plist))
            metadata = read_ipa_metadata(path)
        self.assertEqual(metadata.bundle_identifier, "com.example.App")
        self.assertEqual(metadata.version, "1.2.3")
        self.assertEqual(metadata.build_version, "45")


def json_to_plist(value):
    import plistlib

    return plistlib.dumps(value)


if __name__ == "__main__":
    unittest.main()
