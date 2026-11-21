import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import site004_release as release


class Site004Tests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.home = Path(self.context.name)
        self.root = self.home / 'root'
        self.root.mkdir()
        self.file = self.root / 'index.html'
        self.original = (b'<html><main><a href="mailto:Angarlp@yandex.ru">Contact</a>'
                         b'<p>Angarlp@yandex.ru</p></main>'
                         b'<form action="/api/lead.php"><input value="recipient-unchanged"></form>'
                         b'<script>var recipient="internal@example.com";</script></html>')
        self.file.write_bytes(self.original)
        self.backup = self.home / 'backup'
        self.manifest = self.home / 'manifest.json'
        data = {
            'domain': 'смартангар.рф', 'root': str(self.root),
            'files': [{
                'path': 'index.html', 'sha256': hashlib.sha256(self.original).hexdigest(),
                'edits': [{'before': 'mailto:Angarlp@yandex.ru'},
                          {'before': '<p>Angarlp@yandex.ru</p>'}],
            }],
        }
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def run_operation(self, action):
        return release.execute(action, self.root, self.manifest, self.backup)

    def test_inventory_only_reports_matching_files(self):
        result = self.run_operation('inventory')
        self.assertEqual(result['files'][0]['current_email_count'], 2)
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_prepare_publish_rollback_preserves_forms(self):
        self.assertEqual(self.run_operation('prepare')['prepared'], 1)
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(self.run_operation('publish')['updated'], 1)
        updated = self.file.read_bytes()
        self.assertEqual(updated.count(b'smartangar@yandex.ru'), 2)
        self.assertNotIn(b'Angarlp@yandex.ru', updated)
        self.assertIn(b'<form action="/api/lead.php"><input value="recipient-unchanged"></form>', updated)
        self.assertEqual(self.run_operation('rollback')['updated'], 1)
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_script_email_replacement_refused(self):
        with self.assertRaises(ValueError):
            release.apply_exact_edits(b'<script>const email="Angarlp@yandex.ru"</script>',
                                     [{'before': 'Angarlp@yandex.ru'}])

    def test_unclosed_form_email_replacement_refused(self):
        with self.assertRaises(ValueError):
            release.apply_exact_edits(b'<form><p>Angarlp@yandex.ru</p>',
                                     [{'before': 'Angarlp@yandex.ru'}])

    def test_email_in_non_mailto_attribute_refused(self):
        with self.assertRaises(ValueError):
            release.apply_exact_edits(b'<input value="Angarlp@yandex.ru">',
                                     [{'before': 'Angarlp@yandex.ru'}])

    def test_form_email_replacement_refused(self):
        with self.assertRaises(ValueError):
            release.apply_exact_edits(b'<form><input value="Angarlp@yandex.ru"></form>',
                                     [{'before': 'Angarlp@yandex.ru'}])

    def test_changed_manifest_rejected(self):
        self.run_operation('prepare')
        obj = json.loads(self.manifest.read_text())
        obj['files'][0]['edits'].pop()
        self.manifest.write_text(json.dumps(obj), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_operation('publish')
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_changed_file_rejected(self):
        self.run_operation('prepare')
        self.file.write_bytes(self.original + b'changed')
        with self.assertRaises(ValueError):
            self.run_operation('publish')

    def test_symlink_rejected(self):
        symlink = self.root / 'alias.html'
        symlink.symlink_to('index.html')
        with self.assertRaises(ValueError):
            release.inspect_path(self.root, 'alias.html')

    def test_other_domain_rejected(self):
        obj = json.loads(self.manifest.read_text())
        obj['domain'] = 'смарт-ангар.рф'
        self.manifest.write_text(json.dumps(obj), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_operation('prepare')

    def test_backup_cannot_be_overwritten(self):
        self.run_operation('prepare')
        with self.assertRaises(FileExistsError):
            self.run_operation('prepare')


if __name__ == '__main__':
    unittest.main()
