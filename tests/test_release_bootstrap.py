"""Exercise the embedded curl bootstrap without network or a real terminal."""
import ast
import builtins
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def execute(self, *, bad_hash=False, extra_file=False):
        names = {'Install.command', 'scripts/installer.py', 'scripts/release_files.py',
                 'scripts/common.py', 'scripts/https_transport.py'}
        payloads = {name: b'# fixture\n' for name in names}
        if extra_file:
            payloads['../escaped'] = b'escape'
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in payloads.items():
                archive.writestr(name, data)
        data = output.getvalue()
        version = 'v0.1.0-coloros17-r1'
        receipt = {'project': 'ColorOS-AVD', 'format': 1, 'version': version,
                   'firmware_manifest_sha256': '0' * 64,
                   'archive': {'name': 'ColorOS-AVD-Installer-' + version + '.zip',
                               'size': len(data), 'sha256': '0' * 64 if bad_hash else hashlib.sha256(data).hexdigest()},
                   'files': {name: {'size': len(payloads[name]), 'sha256': hashlib.sha256(payloads[name]).hexdigest()} for name in names}}
        source = (REPO / 'install.sh').read_text().split("COLOROS_BOOTSTRAP_PY'\n", 1)[1].rsplit('\nCOLOROS_BOOTSTRAP_PY', 1)[0]
        tree = ast.parse(source)
        selected = [node for node in tree.body if
                    isinstance(node, ast.FunctionDef) and node.name == 'metadata'
                    or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('BASE', 'ALLOWED') for t in node.targets)]
        selected.append(tree.body[-1])
        code = compile(ast.Module(body=selected, type_ignores=[]), '<bootstrap>', 'exec')
        real_open = builtins.open

        def opened(path, *args, **kwargs):
            return io.StringIO('') if path == '/dev/tty' else real_open(path, *args, **kwargs)

        def response(url, timeout):
            if url.endswith('installer.json'):
                return io.BytesIO(json.dumps(receipt).encode())
            self.assertIn('/download/' + version + '/', url)
            return io.BytesIO(data)

        namespace = {'Path': Path, 'PurePosixPath': PurePosixPath, 'json': json, 're': re,
                     'hashlib': hashlib, 'sys': sys, 'subprocess': subprocess, 'tempfile': tempfile,
                     'zipfile': zipfile, 'secure_urlopen': response}
        with patch('builtins.open', side_effect=opened), patch.object(subprocess, 'call', return_value=0) as run:
            with self.assertRaises(SystemExit) as result:
                exec(code, namespace)
            return result.exception.code, run

    def test_verified_installer_receives_tty_and_pinned_release(self):
        status, run = self.execute()
        self.assertEqual(status, 0)
        args = run.call_args.args[0]
        self.assertIn('--manifest-sha256', args)
        self.assertIn('v0.1.0-coloros17-r1', args)
        self.assertIn('stdin', run.call_args.kwargs)

    def test_archive_hash_failure_never_runs_installer(self):
        status, run = self.execute(bad_hash=True)
        self.assertIn('checksum mismatch', status)
        run.assert_not_called()

    def test_skip_oobe_option_is_forwarded_to_installer(self):
        with patch.object(sys, 'argv', ['-', '--skip-oobe']):
            status, run = self.execute()
        self.assertEqual(status, 0)
        self.assertIn('--skip-oobe', run.call_args.args[0])

    def test_unlisted_zip_path_never_runs_installer(self):
        status, run = self.execute(extra_file=True)
        self.assertIn('Unexpected installer archive entry', status)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
