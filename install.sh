#!/bin/bash
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  echo '需要 Python 3。请安装 Python 3 后重新执行。' >&2
  exit 1
fi
python3 - "$@" <<'COLOROS_BOOTSTRAP_PY'
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import tempfile
import zipfile

if platform.system() != 'Darwin' or platform.machine() != 'arm64':
    raise SystemExit('ColorOS-AVD 需要 Apple Silicon Mac。')
# Adapted from NEORUAA/HyperOS-AVD at 11e1abe0e3.
"""Use verified macOS HTTPS when Python's separate CA store cannot verify TLS.

The bootstrap embeds this exact source before the installer is available.
Never import all keychain certificates as anchors or disable certificate checks.
"""
import http.client as _tls_http
import io as _tls_io
import os as _tls_os
import platform as _tls_platform
import ssl as _tls_ssl
import subprocess as _tls_subprocess
import tempfile as _tls_tempfile
import urllib.error as _tls_error
import urllib.parse as _tls_parse
import urllib.request as _tls_request


def _certificate_failure(error):
    if isinstance(error, _tls_error.URLError):
        error = error.reason
    return isinstance(error, _tls_ssl.SSLCertVerificationError)


class _MacHTTPSResponse:
    """Stream curl headers and body without buffering release archives in RAM."""
    def __init__(self, request, timeout):
        self.url = request.full_url
        self.timeout = timeout
        self.closed = False
        self.finished = False
        self.process = None
        self.stderr = _tls_tempfile.TemporaryFile()
        args = ['/usr/bin/curl', '--disable', '--silent', '--show-error', '--fail',
                '--location', '--globoff', '--max-redirs', '10', '--proto', '=https',
                '--proto-redir', '=https', '--connect-timeout', str(timeout),
                '--speed-limit', '1', '--speed-time', str(timeout),
                '--dump-header', '-']
        # Explicit CA files must retain their authority over native system trust.
        if _tls_os.environ.get('SSL_CERT_FILE'):
            args += ['--cacert', _tls_os.environ['SSL_CERT_FILE']]
        # Python also discovers macOS system proxies; curl only discovers env.
        proxies = _tls_request.getproxies()
        proxy = proxies.get('https') or proxies.get('all')
        if proxy:
            args += ['--proxy', proxy]
        host = _tls_parse.urlsplit(self.url).hostname
        if 'no' in proxies:
            # Keep the complete exclusion list for CDN redirects, not just the
            # first hostname; --noproxy overrides curl's inherited NO_PROXY.
            args += ['--noproxy', proxies['no']]
        elif host and _tls_request.proxy_bypass(request.host):
            args += ['--noproxy', host]
        for name, value in request.header_items():
            if any(char in name + value for char in '\r\n\x00'):
                self.stderr.close()
                raise ValueError('Invalid HTTPS request header.')
            args += ['--header', name + ': ' + value]
        args += ['--url', self.url]
        try:
            self.process = _tls_subprocess.Popen(args, stdin=_tls_subprocess.DEVNULL,
                stdout=_tls_subprocess.PIPE, stderr=self.stderr)
            self._headers()
        except BaseException:
            self.close()
            raise

    def _failure(self):
        # curl errors can contain proxy credentials or signed redirect URLs.
        # Return only its stable exit code, never stderr or the command line.
        code = self.process.returncode
        return _tls_error.URLError('macOS HTTPS transfer failed (curl exit '
            + str(code) + '); TLS certificate and hostname verification remain enabled.')

    def _complete(self):
        if self.finished:
            return
        try:
            self.process.wait(timeout=self.timeout + 2)
        except _tls_subprocess.TimeoutExpired:
            raise _tls_error.URLError('macOS HTTPS transfer timed out.') from None
        self.finished = True
        if self.process.returncode:
            raise self._failure()

    def _headers(self):
        # --location emits each response header block, but only the final body.
        # Skip informational, CONNECT proxy and followed redirect responses.
        for _ in range(32):
            line = self.process.stdout.readline(65537)
            if not line:
                self._complete()
                raise _tls_error.URLError('Missing HTTPS response headers.')
            if len(line) > 65536 or not line.startswith(b'HTTP/'):
                raise _tls_error.URLError('Invalid HTTPS response status.')
            fields = line.rstrip(b'\r\n').split(b' ', 2)
            if len(fields) < 2 or not fields[1].isdigit():
                raise _tls_error.URLError('Invalid HTTPS response status.')
            status = int(fields[1])
            block = bytearray()
            for _ in range(100):
                header = self.process.stdout.readline(65537)
                block.extend(header)
                if not header or len(block) > 65536:
                    raise _tls_error.URLError('Invalid or oversized HTTPS response headers.')
                if header in (b'\r\n', b'\n'):
                    break
            else:
                raise _tls_error.URLError('Too many HTTPS response headers.')
            headers = _tls_http.parse_headers(_tls_io.BytesIO(block))
            if status < 200 or (status == 200 and len(fields) == 3
                    and fields[2].lower() == b'connection established'):
                continue
            if 300 <= status < 400 and headers.get('Location'):
                continue
            if not 200 <= status < 300:
                error = _tls_error.HTTPError(self.url, status, 'HTTPS request failed', headers, None)
                error.close()
                raise error
            self.status = status
            self.headers = headers
            return
        raise _tls_error.URLError('Too many HTTPS response header blocks.')

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if self.closed:
            raise ValueError('HTTPS response is closed.')
        if size == 0:
            return b''
        data = self.process.stdout.read(size)
        if size < 0 or not data or len(data) < size:
            self._complete()
        return data

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except _tls_subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=2)
                    except _tls_subprocess.TimeoutExpired:
                        raise _tls_error.URLError('Could not reap owned macOS HTTPS transfer.') from None
        finally:
            if self.process is not None:
                self.process.stdout.close()
            self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _mac_certificate_response(value, timeout, error):
    request = value if isinstance(value, _tls_request.Request) else _tls_request.Request(value)
    if (not _certificate_failure(error) or _tls_platform.system() != 'Darwin'
            or _tls_parse.urlsplit(request.full_url).scheme != 'https'
            or request.get_method() != 'GET' or request.data is not None):
        raise error
    # SecureTransport does not reliably support OpenSSL hashed CA directories.
    # Never silently replace an explicit directory restriction with native CAs.
    if _tls_os.environ.get('SSL_CERT_DIR'):
        raise _tls_error.URLError('TLS verification failed with explicit SSL_CERT_DIR; '
            'macOS fallback cannot preserve that CA directory. Configure a trusted SSL_CERT_FILE.') from error
    if not _tls_os.path.isfile('/usr/bin/curl'):
        raise error
    return _MacHTTPSResponse(request, timeout)


def secure_urlopen(value, timeout=30):
    try:
        return _tls_request.urlopen(value, timeout=timeout)
    except (_tls_ssl.SSLCertVerificationError, _tls_error.URLError) as error:
        return _mac_certificate_response(value, timeout, error)


def secure_urlretrieve(url, filename):
    """Retain urllib's normal path and use the same verified streaming fallback."""
    try:
        return _tls_request.urlretrieve(url, filename)
    except (_tls_ssl.SSLCertVerificationError, _tls_error.URLError) as error:
        with _mac_certificate_response(url, 30, error) as response:
            with open(filename, 'wb') as output:
                while block := response.read(128 * 1024):
                    output.write(block)
            return str(filename), response.headers


BASE = 'https://github.com/YuKongA/ColorOS-AVD/releases/latest/download/'
ALLOWED = {'Install.command', 'scripts/installer.py', 'scripts/release_files.py',
           'scripts/common.py', 'scripts/https_transport.py'}

def metadata(url):
    with secure_urlopen(url, timeout=30) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise RuntimeError('Installer metadata exceeded its size limit.')
    return json.loads(content)

try:
    print('正在获取 ColorOS-AVD 安装向导……', flush=True)
    receipt = metadata(BASE + 'installer.json')
    version = receipt.get('version', '')
    if (receipt.get('project') != 'ColorOS-AVD' or receipt.get('format') != 1
            or not re.fullmatch(r'v[0-9A-Za-z_.-]+', version)
            or set(receipt.get('files', {})) != ALLOWED
            or not re.fullmatch('[0-9a-f]{64}', receipt.get('firmware_manifest_sha256', ''))):
        raise RuntimeError('Unsupported installer receipt.')
    archive = receipt['archive']
    if (archive.get('name') != 'ColorOS-AVD-Installer-' + version + '.zip'
            or type(archive.get('size')) is not int or not 0 < archive['size'] < 8 * 1024 * 1024
            or not re.fullmatch('[0-9a-f]{64}', archive.get('sha256', ''))):
        raise RuntimeError('Invalid installer archive.')
    url = 'https://github.com/YuKongA/ColorOS-AVD/releases/download/' + version + '/' + archive['name']
    with tempfile.TemporaryDirectory(prefix='coloros-installer-') as directory:
        root = Path(directory)
        target = root / 'installer.zip'
        with secure_urlopen(url, timeout=30) as response:
            content = response.read(archive['size'] + 1)
        if len(content) != archive['size'] or hashlib.sha256(content).hexdigest() != archive['sha256']:
            raise RuntimeError('Installer archive checksum mismatch.')
        target.write_bytes(content)
        seen = set()
        with zipfile.ZipFile(target) as zipped:
            for item in zipped.infolist():
                name = item.filename
                if name not in ALLOWED or name in seen or item.is_dir():
                    raise RuntimeError('Unexpected installer archive entry.')
                expected = receipt['files'][name]
                if item.file_size != expected['size'] or item.file_size > 2 * 1024 * 1024:
                    raise RuntimeError('Installer file exceeded its expected size.')
                data = zipped.read(item)
                if hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise RuntimeError('Installer file checksum mismatch.')
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                seen.add(name)
        if seen != ALLOWED:
            raise RuntimeError('Installer archive is incomplete.')
        # Both curl | bash and Python's heredoc consume stdin. The wizard
        # reads directly from the terminal, leaving download input separate.
        with open('/dev/tty', 'r') as terminal:
            # Preserve explicit CLI options such as --root, --name and --sdk
            # from curl | bash while pinning the verified release metadata.
            result = subprocess.call([sys.executable, str(root / 'scripts/installer.py'),
                                      '--release', version, '--manifest-sha256',
                                      receipt['firmware_manifest_sha256'], *sys.argv[1:]], stdin=terminal)
        raise SystemExit(result)
except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
    raise SystemExit('安装向导启动失败：' + str(error))
except KeyboardInterrupt:
    raise SystemExit('\n已取消。')
COLOROS_BOOTSTRAP_PY
