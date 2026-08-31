from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.app.service.static_assets import LocalStaticAssets, _is_link_like


class LocalStaticAssetsTests(unittest.TestCase):
    @staticmethod
    def _root(parent: Path) -> Path:
        root = parent / "dist"
        root.mkdir()
        (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
        return root

    def test_normal_compiled_assets_remain_available(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._root(Path(directory))
            assets = root / "assets"
            assets.mkdir()
            (assets / "app-123.js").write_bytes(b"console.log('OpenTCAD');")
            (root / "og.png").write_bytes(b"not-a-decoder-boundary")

            surface = LocalStaticAssets(root)

            self.assertTrue(surface.matches("/"))
            self.assertEqual(surface.read("/").content_type, "text/html; charset=utf-8")
            self.assertEqual(
                surface.read("/assets/app-123.js").body,
                b"console.log('OpenTCAD');",
            )
            self.assertEqual(surface.read("/og.png").content_type, "image/png")
            self.assertFalse(surface.matches("/assets/../index.html"))

    def test_symlink_root_and_index_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._root(parent)
            root_link = parent / "root-link"
            try:
                root_link.symlink_to(root, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Host cannot create test symlinks: {error}")
            with self.assertRaises(TypeError):
                LocalStaticAssets(root_link)

            (root / "index.html").unlink()
            outside = parent / "outside.html"
            outside.write_text("outside", encoding="utf-8")
            (root / "index.html").symlink_to(outside)
            with self.assertRaises(TypeError):
                LocalStaticAssets(root)

    def test_symlink_asset_directory_and_file_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._root(parent)
            outside = parent / "outside"
            outside.mkdir()
            (outside / "escape.js").write_bytes(b"outside")
            asset_directory = root / "assets"
            try:
                asset_directory.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Host cannot create test symlinks: {error}")
            surface = LocalStaticAssets(root)
            with self.assertRaises(FileNotFoundError):
                surface.read("/assets/escape.js")

            asset_directory.unlink()
            asset_directory.mkdir()
            (asset_directory / "escape.js").symlink_to(outside / "escape.js")
            with self.assertRaises(FileNotFoundError):
                surface.read("/assets/escape.js")

    def test_windows_reparse_attribute_is_link_like(self) -> None:
        candidate = Path("reparse-placeholder")
        metadata = SimpleNamespace(st_file_attributes=0x400)
        with (
            patch.object(Path, "lstat", return_value=metadata),
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(Path, "is_junction", return_value=False),
        ):
            self.assertTrue(_is_link_like(candidate))


if __name__ == "__main__":
    unittest.main()
