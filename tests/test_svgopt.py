"""Standard-library tests for the svgopt CLI and path concatenator."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import svgopt

START = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">'
END = '</svg>'

def path(style, x, name='', transform=''):
    ident = f' id="{name}"' if name else ''
    tr = f' transform="{transform}"' if transform else ''
    return f'<path{ident}{tr} style="{style}" d="M{x} 0 h10 v10 h-10 z"/>'

class MergeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.source = Path(self.dir.name) / 'in.svg'
        self.output = Path(self.dir.name) / 'out.svg'

    def merge(self, body):
        self.source.write_text(START + body + END, encoding='utf-8')
        counts = svgopt.merge_file(self.source, self.output)
        result = ET.parse(self.output).getroot()
        return counts, list(result)

    def test_adjacent_opaque_same_color_paths_merge(self):
        style = 'fill:#f00;stroke:none'
        counts, paths = self.merge(path(style, 0, 'first') + path(style, 10, 'second'))
        self.assertEqual(counts, (1, 1))
        self.assertEqual(len(paths), 1)
        self.assertIn('M10', paths[0].get('d'))
        self.assertEqual(paths[0].get('id'), 'first')

    def test_different_color_or_interleaved_line_prevents_merge(self):
        red = 'fill:#f00;stroke:none'
        blue = 'fill:#00f;stroke:none'
        counts, paths = self.merge(path(red, 0) + path(blue, 10) + path(red, 20))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(len(paths), 3)

    def test_transform_mismatch_prevents_merge(self):
        style = 'fill:#f00;stroke:none'
        counts, paths = self.merge(path(style, 0, transform='translate(1)') + path(style, 10, transform='translate(2)'))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(len(paths), 2)

    def test_transparency_is_not_merged(self):
        style = 'fill:#f00;stroke:none;fill-opacity:0.5'
        counts, paths = self.merge(path(style, 0) + path(style, 10))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(len(paths), 2)

    def test_referenced_ids_are_protected(self):
        style = 'fill:#f00;stroke:none'
        body = path(style, 0, 'first') + path(style, 10, 'used') + '<use href="#used"/>'
        counts, paths = self.merge(body)
        self.assertEqual(counts, (0, 0))
        self.assertEqual(len(paths), 3)

    def test_relative_first_move_is_reset_before_concatenation(self):
        s = 'fill:#f00;stroke:none'
        a = '<path style="' + s + '" d="m1 2 h2 z"/>'
        b = '<path style="' + s + '" d="m4 5 h3 z"/>'
        counts, paths = self.merge(a + b)
        self.assertEqual(counts, (1, 1))
        self.assertIn('M0 0 m4 5', paths[0].get('d'))

    def test_embedded_css_skips_merging(self):
        s = 'fill:#f00;stroke:none'
        counts, paths = self.merge('<style>path{opacity:1}</style>' + path(s, 0) + path(s, 10))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(len(paths), 3)

class CLITests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = Path(self.dir.name)

    def test_glob_skips_existing_optimized_files(self):
        (self.folder / 'a.svg').write_text(START + END)
        (self.folder / 'a_opt.svg').write_text(START + END)
        (self.folder / 'b.svg').write_text(START + END)
        result = svgopt.expand_inputs([str(self.folder / '*.svg')], recursive=False)
        self.assertEqual({p.name for p in result}, {'a.svg', 'b.svg'})

    def test_mock_svgopt_pipeline_keeps_original_and_single_output(self):
        source = self.folder / 'figure.svg'
        data = START + path('fill:#f00;stroke:none', 0) + path('fill:#f00;stroke:none', 10) + END
        source.write_text(data, encoding='utf-8')
        original_bytes = source.read_bytes()
        def fake_svgo(command, **kwargs):
            import shutil
            from types import SimpleNamespace
            shutil.copyfile(command[command.index('-i') + 1], command[command.index('-o') + 1])
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(svgopt.subprocess, 'run', side_effect=fake_svgo):
            info = svgopt.optimize_file(source, self.folder / 'figure_opt.svg', 'svgo', 5, False, False)
        self.assertEqual(info[2:], (1, 1))
        self.assertEqual(original_bytes, source.read_bytes())
        self.assertTrue((self.folder / 'figure_opt.svg').is_file())

if __name__ == '__main__':
    unittest.main()
