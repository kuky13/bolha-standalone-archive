# SPDX-License-Identifier: GPL-3.0-only
"""Instaladores reais somente no Windows, sempre em perfil /TEST descartável.

python scripts/test_windows_native.py --installer release/Bolha-Setup-0.3.0-x64.exe \
  --target-installer validation/update-feed/Bolha-Setup-0.3.1-x64.exe --output validation/windows-native

Não compila nem baixa instaladores. O modo legado é exclusivo do runner Windows
hospedado e descartável do GitHub; nunca pode ser executado no notebook do usuário.
"""
import argparse
import base64
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def digest(path, algorithm='sha256'):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, algorithm).digest()


def installer_version(path):
    match = re.fullmatch(r'Bolha-Setup-(\d+\.\d+\.\d+)-x64\.exe', Path(path).name)
    if not match:
        raise ValueError('Nome de instalador inválido: '+str(path))
    return match[1]


def wait_for(description, predicate, timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.2)
    raise TimeoutError(description)


class Feed:
    """Servidor fechado a nomes conhecidos, escutando somente em 127.0.0.1."""
    def __init__(self, installer):
        self.installer = Path(installer).resolve()
        self.version = installer_version(installer)
        self.size = self.installer.stat().st_size
        self.sha256 = digest(installer).hex()
        self.sha512 = base64.b64encode(digest(installer, 'sha512')).decode('ascii')
        self.mode = 'valid'
        self.requests = []
        self.interrupted = False
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                name = urlsplit(self.path).path
                feed.requests.append(dict(path=name, mode=feed.mode, at=time.time()))
                if feed.mode == 'offline':
                    self.send_error(503)
                    return
                if name == '/release.json':
                    content = json.dumps(feed.release()).encode()
                elif name == '/SHA256SUMS.txt':
                    content = feed.manifest()
                elif name == '/latest.yml':
                    content = feed.latest()
                elif name == '/'+feed.installer.name:
                    self.send_response(200)
                    self.send_header('Content-Length', str(feed.size))
                    self.end_headers()
                    try:
                        with feed.installer.open('rb') as source:
                            if feed.mode == 'interrupted':
                                self.wfile.write(source.read(min(65536, max(1, feed.size//2))))
                                self.wfile.flush()
                                feed.interrupted = True
                                self.connection.shutdown(socket.SHUT_RDWR)
                                self.connection.close()
                            else:
                                shutil.copyfileobj(source, self.wfile, 128*1024)
                    except (OSError, ConnectionError):
                        pass
                    return
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (OSError, ConnectionError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}/'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def manifest(self):
        checksum = '0'*64 if self.mode == 'checksum' else self.sha256
        return f'{checksum}  {self.installer.name}\n'.encode()

    def latest(self):
        return (f'version: {self.version}\nfiles:\n  - url: {self.installer.name}\n'
                f'    sha512: {self.sha512}\n    size: {self.size}\n'
                f'path: {self.installer.name}\nsha512: {self.sha512}\n').encode()

    def release(self):
        return dict(tag_name='v'+self.version, draft=False, prerelease=False, assets=[
            dict(name=self.installer.name, size=self.size, browser_download_url=self.url+self.installer.name),
            dict(name='SHA256SUMS.txt', size=len(self.manifest()), browser_download_url=self.url+'SHA256SUMS.txt'),
        ])

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def legacy_allowed(environ=None, hostname=None):
    environ = os.environ if environ is None else environ
    hostname = platform.node() if hostname is None else hostname
    return (hostname.casefold() != 'kukybook26'
            and environ.get('GITHUB_ACTIONS') == 'true'
            and environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and environ.get('RUNNER_OS') == 'Windows')


def test_environment(data, install, report, feed=None):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('BOLHA_TEST')}
    environment.update(BOLHA_TEST='1', BOLHA_TEST_STATUS='1', BOLHA_TEST_ALLOW_STOP='1',
                       BOLHA_TEST_USER_DATA=str(Path(data).resolve()),
                       BOLHA_TEST_INSTALL_DIR=str(Path(install).resolve()),
                       BOLHA_TEST_REPORT=str(Path(report).resolve()), BOLHA_TEST_DURATION='120')
    if feed:
        environment['BOLHA_TEST_UPDATE_URL'] = feed
    return environment


def registry_fingerprint():
    """Só lê chaves específicas da Bolha; não inclui seus valores no relatório."""
    import winreg
    values = []
    for location in (r'Software\efdda9e4-adbf-5481-bf79-1ee5a33cbceb',
                     r'Software\Microsoft\Windows\CurrentVersion\Uninstall\efdda9e4-adbf-5481-bf79-1ee5a33cbceb',
                     r'Software\Microsoft\Windows\CurrentVersion\Run'):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, location, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                if location.endswith('Run'):
                    try:
                        value, kind = winreg.QueryValueEx(key, 'Bolha')
                    except FileNotFoundError:
                        values.append((location, None))
                    else:
                        values.append((location, 'Bolha', value, kind))
                    continue
                index = 0
                while True:
                    try:
                        name, value, kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    values.append((location, name, value, kind))
                    index += 1
        except FileNotFoundError:
            values.append((location, None))
    return hashlib.sha256(repr(sorted(values, key=repr)).encode()).hexdigest()


def process_alive(pid, expected_exe):
    """Consulta somente o PID com caminho exato do executável de teste."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, int(pid))
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: o PID já não existe.
            return False
        raise ctypes.WinError(error)
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return False
        if status != 258:
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            error = ctypes.get_last_error()
            # O Windows pode negar o caminho um instante antes de sinalizar a saída.
            if kernel.WaitForSingleObject(handle, 100) == 0:
                return False
            raise ctypes.WinError(error)
        if Path(path.value).resolve() != Path(expected_exe).resolve():
            raise AssertionError('PID não pertence ao executável isolado esperado.')
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def process_cpu_seconds(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),)*4
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ((system.dwHighDateTime << 32) + system.dwLowDateTime +
                (user.dwHighDateTime << 32) + user.dwLowDateTime)/10_000_000
    finally:
        kernel.CloseHandle(handle)


def validate_metrics(metrics, health):
    assert health.get('ready') is True and health.get('neurons') == 470
    assert metrics.get('version') == health.get('version'), 'Relatório pertence a outra versão.'
    assert type(metrics.get('pid')) is int and metrics['pid'] == health.get('pid'), 'Relatório pertence a outra execução.'
    assert metrics.get('healthy') is True and metrics.get('neurons') == 470, 'Relatório saudável ausente.'
    assert metrics.get('frameCount', 0) > 0 and metrics.get('thinkCount', 0) > 0
    return metrics


class NativeValidation:
    def __init__(self, installer, target, output, keep=False):
        self.installer, self.target = Path(installer).resolve(), Path(target).resolve()
        self.base_version, self.target_version = installer_version(installer), installer_version(target)
        assert tuple(map(int, self.target_version.split('.'))) > tuple(map(int, self.base_version.split('.')))
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='bolha-native-validation-'+uuid.uuid4().hex[:8]+'-')).resolve()
        self.token = uuid.uuid4().hex
        write_json(self.root/'validation-owner.json', dict(token=self.token))
        self.install, self.data = self.root/'app', self.root/'data'
        self.exe = self.install/'Bolha.exe'
        self.keep = keep
        self.processes = []
        self.results = []
        self.report = dict(platform=platform.platform(), mode='isolated-native',
                           base=self.base_version, target=self.target_version,
                           workspace=str(self.root), results=self.results)
        self.current_report = None

    def record(self, scenario, **data):
        self.results.append(dict(scenario=scenario, passed=True, **data))
        write_json(self.output/'report.json', self.report)
        print('PASS', scenario, flush=True)

    def environment(self, scenario, feed=None):
        self.current_report = self.output/(scenario+'-runtime.json')
        self.current_report.unlink(missing_ok=True)
        return test_environment(self.data, self.install, self.current_report, feed)

    def install_package(self, package, environment, force=False, success=True):
        arguments = [str(package), '/S', '/TEST']
        if force:
            arguments.append('--force-run')
        arguments.append('/D='+environment['BOLHA_TEST_INSTALL_DIR'])
        result = subprocess.run(arguments, env=environment, timeout=180, capture_output=True)
        if success:
            assert result.returncode == 0, f'Instalador retornou {result.returncode}'
        return result.returncode

    def launch(self, scenario, feed=None):
        for name in ('health.json', 'update-state.json', 'test-stop.request'):
            (self.data/name).unlink(missing_ok=True)
        environment = self.environment(scenario, feed)
        process = subprocess.Popen([str(self.exe)], env=environment, cwd=self.install,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process

    def healthy(self, version, timeout=90):
        def check():
            health = read_json(self.data/'health.json') or {}
            if health.get('version') == version and health.get('ready') is True and health.get('neurons') == 470:
                if process_alive(health.get('pid'), self.exe):
                    return health
        return wait_for('Abertura saudável da versão '+version, check, timeout)

    def state(self, phase, timeout=120):
        return wait_for('Estado de atualização '+phase,
                        lambda: (value if (value := read_json(self.data/'update-state.json')) and value.get('phase') == phase
                                 and (phase != 'ready' or isinstance(value.get('installAt'), (int, float))) else None), timeout)

    def stop(self, health=None):
        health = health or read_json(self.data/'health.json') or {}
        pid = health.get('pid')
        if pid and process_alive(pid, self.exe):
            (self.data/'test-stop.request').write_text('isolated validation complete', encoding='utf-8')
            wait_for('Encerramento gracioso do aplicativo isolado', lambda: not process_alive(pid, self.exe), 25)
        for process in self.processes:
            if process.poll() is not None:
                process.wait()
        metrics = read_json(self.current_report) or {}
        return validate_metrics(metrics, health)

    def preserved(self):
        preferences = read_json(self.data/'config.json')['preferences']
        assert preferences['avatarSize'] == 152
        assert all(preferences[key] is False for key in ('senseApp','senseIdle','senseCursor','senseWindows'))
        memory = read_json(self.data/'brain/bolha/nervous.json')
        assert memory['seed'] == 1313 and memory['learned']['PRESO']['CALM'] > .04

    def run(self):
        before_registry = registry_fingerprint()
        try:
            # Uma pasta estrangeira jamais é renomeada/substituída.
            foreign = self.root/'foreign'
            foreign.mkdir()
            sentinel = foreign/'documento-do-usuario.txt'
            sentinel.write_bytes(b'preservar-'+self.token.encode())
            expected = sentinel.read_bytes()
            environment = test_environment(self.root/'foreign-data', foreign, self.output/'foreign-runtime.json')
            code = self.install_package(self.installer, environment, success=False)
            assert code != 0 and sentinel.read_bytes() == expected and not (foreign/'Bolha.exe').exists()
            assert not list(self.root.glob('foreign.stage-*')) and not list(self.root.glob('foreign.rollback-*'))
            self.record('foreign_directory_preserved', returncode=code)

            # Destino novo já existente e vazio: caso diferente de pasta estrangeira.
            self.install.mkdir()
            self.install_package(self.installer, self.environment('clean'))
            assert (self.install/'bolha-test-install.flag').read_text() == 'isolated'
            self.launch('clean')
            health = self.healthy(self.base_version)
            cpu_before, wall_before = process_cpu_seconds(health['pid']), time.monotonic()
            time.sleep(1)
            elapsed = time.monotonic()-wall_before
            cpu_percent = (process_cpu_seconds(health['pid'])-cpu_before)/elapsed*100
            metrics = self.stop()
            self.record('clean_install_existing_empty_directory', metrics=metrics,
                        cpuPercentOfOneCore=round(cpu_percent, 2), cpuSampleSeconds=round(elapsed, 3))

            configuration = read_json(self.data/'config.json') or dict(schemaVersion=1, preferences={})
            configuration.setdefault('preferences', {})
            configuration['preferences'].update(avatarSize=152, senseApp=False, senseIdle=False, senseCursor=False, senseWindows=False)
            write_json(self.data/'config.json', configuration)
            memory_file = self.data/'brain/bolha/nervous.json'
            memory = read_json(memory_file)
            assert memory['seed'] == 1313
            memory['learned']['PRESO']['CALM'] = .06
            write_json(memory_file, memory)

            with Feed(self.target) as feed:
                for mode in ('checksum', 'interrupted'):
                    feed.mode = mode
                    self.launch(mode, feed.url)
                    self.state('error')
                    health = self.healthy(self.base_version)
                    assert not list((self.data/'update-cache').rglob('*.part'))
                    if mode == 'interrupted':
                        assert feed.interrupted
                    self.stop(health)
                    self.preserved()
                    self.record(mode+'_rejected_app_continues')

                feed.mode = 'valid'
                until = int(time.time()*1000)+3600000
                write_json(self.data/'update-deferred.json', dict(version=self.target_version, until=until))
                self.launch('deferred', feed.url)
                state = self.state('ready')
                assert state['installAt']-time.time()*1000 > 3500000
                pending = read_json(self.data/'pending-update.json')
                cached = Path(pending['installer']).resolve()
                assert cached.is_relative_to(self.data/'update-cache')
                assert digest(cached).hex() == pending['sha256'] == feed.sha256
                self.stop(self.healthy(self.base_version))
                assert read_json(self.data/'update-deferred.json')['until'] == until
                self.record('one_hour_deferral_persistent', until=until)

                feed.mode = 'offline'
                request_count = len(feed.requests)
                self.launch('offline-resume', feed.url)
                state = self.state('ready')
                assert state['installAt']-time.time()*1000 > 3450000
                self.stop(self.healthy(self.base_version))
                assert len(feed.requests) == request_count, 'Cache validado deveria retomar sem rede.'
                self.record('restart_offline_uses_verified_pending')

                # Mesmo cache alterado após download deve ser recusado antes de executar.
                with cached.open('ab') as output:
                    output.write(b'invalid-test-size')
                self.launch('tampered-cache', feed.url)
                self.state('error')
                self.stop(self.healthy(self.base_version))
                self.preserved()
                shutil.copyfile(self.target, cached)
                self.record('tampered_cached_installer_rejected')

                # A falha de abertura do alvo acontece antes de Qt/dados; recupera base.
                old_inventory = digest(self.install/'installed-files.json').hex()
                environment = self.environment('rollback', feed.url)
                environment['BOLHA_TEST_FAIL_START'] = self.target_version
                (self.data/'health.json').unlink(missing_ok=True)
                code = self.install_package(self.target, environment, force=True, success=False)
                assert code != 0
                health = self.healthy(self.base_version)
                assert digest(self.install/'installed-files.json').hex() == old_inventory
                self.stop(health)
                self.preserved()
                assert not self.install.with_name(self.install.name+'.transaction.ini').exists()
                self.record('failed_target_start_restores_previous_installation', returncode=code)

                # A última etapa realmente aguarda os 30s e instala sem chamada manual.
                feed.mode = 'valid'
                (self.data/'update-deferred.json').unlink(missing_ok=True)
                self.launch('automatic-update', feed.url)
                ready = self.state('ready')
                deadline = ready.get('installAt', 0)
                assert 15000 < deadline-time.time()*1000 <= 31000
                source_health = self.healthy(self.base_version)
                target_health = self.healthy(self.target_version, 180)
                assert target_health['pid'] != source_health['pid']
                assert time.time()*1000 >= deadline-1000, 'Instalação iniciou antes da contagem de 30s.'
                wait_for('Limpeza após versão saudável', lambda: not cached.exists() and not (self.data/'pending-update.json').exists()
                         and not self.install.with_name(self.install.name+'.transaction.ini').exists(), 90)
                target_metrics = self.stop(target_health)
                self.preserved()
                assert not list((self.data/'update-cache').rglob('*.part'))
                assert not (self.install/'resources/app.asar').exists()
                self.record('automatic_30_second_update_and_cleanup', installAt=deadline,
                            healthy=target_health, metrics=target_metrics)
                write_json(self.output/'feed-requests.json', feed.requests)

            assert registry_fingerprint() == before_registry, '/TEST alterou o registro real da Bolha.'
            for name in ('config.json', 'health.json', 'update-state.json'):
                source = self.data/name
                if source.is_file():
                    shutil.copy2(source, self.output/('final-'+name))
            shutil.copy2(self.data/'brain/bolha/nervous.json', self.output/'final-nervous.json')
            self.record('preferences_seed_learning_and_registry_preserved')
            self.report['passed'] = True
        except BaseException as error:
            self.report.update(passed=False, error=f'{type(error).__name__}: {error}')
            raise
        finally:
            self.report['registryUnchanged'] = registry_fingerprint() == before_registry
            self.report['workspaceRetained'] = self.keep or not self.report.get('passed', False)
            health = read_json(self.data/'health.json') or {}
            try:
                if health.get('pid') and process_alive(health['pid'], self.exe):
                    self.stop(health)
            except (OSError, AssertionError, TimeoutError) as cleanup_error:
                self.report['cleanupWarning'] = str(cleanup_error)
                self.report['workspaceRetained'] = True
            write_json(self.output/'report.json', self.report)
            # Só processos Popen deste driver podem ser terminados por segurança.
            for process in self.processes:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
            if not self.report['workspaceRetained']:
                assert read_json(self.root/'validation-owner.json') == dict(token=self.token)
                try:
                    shutil.rmtree(self.root)
                except OSError as cleanup_error:
                    self.report.update(workspaceRetained=True, cleanupWarning=str(cleanup_error))
                    write_json(self.output/'report.json', self.report)


def verify_legacy_owner(data, install, token):
    data, install = Path(data), Path(install)
    root = install.parent
    if (not re.fullmatch('[a-f0-9]{32}', token) or data.name.lower() != 'bolha'
            or install.name != 'app' or not root.name.startswith('bolha-legacy-validation-')):
        raise ValueError('Caminhos de teste legado inválidos.')
    for path in (data, install, root, data/'.bolha-legacy-validation.json', root/'validation-owner.json'):
        if path == install and not path.exists() and not path.is_symlink():
            continue  # O desinstalador próprio pode já ter removido a pasta app.
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('O teste legado não aceita atalhos ou junctions.')
    owner = read_json(data/'.bolha-legacy-validation.json') or {}
    if (owner.get('token') != token or owner.get('createdBy') != 'bolha-legacy-validation'
            or Path(owner.get('data', '')).resolve() != data.resolve()
            or Path(owner.get('install', '')).resolve() != install.resolve()
            or read_json(root/'validation-owner.json') != dict(token=token)):
        raise ValueError('Perfil sem ownership verificável; nenhum arquivo será removido.')
    # Não atravessa um link surgido em qualquer parte do perfil arquivado/removido.
    for base in (data, root):
        for parent, folders, files in os.walk(base, followlinks=False):
            for name in folders+files:
                path = Path(parent)/name
                if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Atalho no perfil de teste; limpeza cancelada.')
    return owner


def legacy_registration(install, version):
    """Prova exata de GUID/caminho, nunca remoção por nome ou substring."""
    import winreg
    guid = 'efdda9e4-adbf-5481-bf79-1ee5a33cbceb'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\'+guid, 0,
                       winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        location = winreg.QueryValueEx(key, 'InstallLocation')[0]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'+guid,
                       0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        installed_version = winreg.QueryValueEx(key, 'DisplayVersion')[0]
        uninstaller = winreg.QueryValueEx(key, 'UninstallString')[0]
    expected = Path(install).resolve()
    if (Path(location).resolve() != expected or installed_version != version
            or uninstaller != '"'+str(expected/'Uninstall Bolha.exe')+'"'):
        raise ValueError('O registro não pertence à instalação isolada esperada.')
    return dict(guid=guid, install=str(expected), version=version)


def legacy_registration_absent():
    import winreg
    for path in ('Software\\efdda9e4-adbf-5481-bf79-1ee5a33cbceb',
                 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\efdda9e4-adbf-5481-bf79-1ee5a33cbceb'):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                               winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
                return False
        except FileNotFoundError:
            pass
    return True


def cleanup_legacy_runner(data, install, token, version, output, report):
    if not legacy_allowed():
        raise PermissionError('Limpeza legada somente no runner GitHub hospedado e descartável.')
    data, install, output = Path(data), Path(install), Path(output)
    verify_legacy_owner(data, install, token)
    health = report.get('health') or {}
    validate_metrics(report.get('metrics') or {}, health)
    assert health['version'] == version
    # O relatório é gravado no início do quit: esperar só o JSON é insuficiente.
    wait_for('Processo Qt ainda está ativo; perfil preservado.',
             lambda: not process_alive(health['pid'], install/'Bolha.exe'), 30)
    inventory = read_json(install/'installed-files.json') or {}
    if (inventory.get('appId') != 'solutions.kuky.bolha' or inventory.get('version') != version
            or (install/'bolha-native-installation.flag').read_text(encoding='utf-8') != 'bolha-native:solutions.kuky.bolha'
            or digest(install/'Bolha.exe').hex() != inventory.get('files', {}).get('Bolha.exe')):
        raise ValueError('Inventário nativo não confere; instalação e perfil preservados.')
    uninstaller = install/'Uninstall Bolha.exe'
    if not uninstaller.is_file() or uninstaller.is_symlink():
        raise ValueError('Desinstalador próprio não encontrado.')
    registration = legacy_registration(install, version)
    evidence = output/('evidence-'+token[:8])
    evidence.mkdir(parents=True)
    shutil.copytree(data, evidence/'profile')
    shutil.copy2(install/'installed-files.json', evidence/'installed-files.json')
    write_json(evidence/'ownership.json', dict(token=token, registration=registration,
               nativePid=health['pid'], nativeProcessExited=True))
    # Executa somente o desinstalador da pasta nova cuja identidade foi provada.
    subprocess.run([str(uninstaller), '/S'], check=True, timeout=90)
    wait_for('Desinstalação própria não concluiu; perfil preservado.',
             lambda: legacy_registration_absent() and not (install/'Bolha.exe').exists(), 60)
    verify_legacy_owner(data, install, token)
    shutil.rmtree(data)
    assert read_json(install.parent/'validation-owner.json') == dict(token=token)
    shutil.rmtree(install.parent)
    return dict(nativeProcessExited=True, profileRemoved=True, installationUninstalled=True,
                registrationRemoved=True, evidence=str(evidence))


def run_legacy(args):
    if not legacy_allowed():
        raise PermissionError('Transição legada exige runner Windows GitHub hospedado e descartável; proibida no kukybook26.')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output/'report.json').unlink(missing_ok=True)
    data = Path(os.environ['APPDATA'])/'bolha'
    if data.exists():
        raise FileExistsError('O runner legado já tem um perfil Bolha. Use um runner descartável novo.')
    if not legacy_registration_absent():
        raise FileExistsError('O runner legado já tem uma instalação Bolha registrada.')
    root = Path(tempfile.mkdtemp(prefix='bolha-legacy-validation-')).resolve()
    token = uuid.uuid4().hex
    write_json(root/'validation-owner.json', dict(token=token))
    with Feed(args.installer) as feed:
        request = dict(installer=str(Path(args.legacy_installer).resolve()), targetVersion=installer_version(args.installer),
                       install=str(root/'app'), data=str(data), feed=feed.url, output=str(output),
                       playwrightRoot=str(Path(args.playwright_root).resolve()), ownerToken=token)
        write_json(output/'legacy-request.json', request)
        try:
            subprocess.run(['node', str(Path(__file__).with_name('test_windows_legacy.mjs')),
                            str(output/'legacy-request.json')], check=True, timeout=300)
            report = read_json(output/'report.json') or {}
            assert report.get('passed') is True, 'Migração não confirmou sucesso.'
            report['cleanup'] = cleanup_legacy_runner(data, root/'app', token, request['targetVersion'], output, report)
            write_json(output/'report.json', report)
        except (OSError, ValueError, AssertionError, subprocess.SubprocessError) as error:
            report = read_json(output/'report.json') or {}
            report.update(passed=False, mode='disposable-legacy', error=str(error), workspaceRetained=str(root))
            write_json(output/'report.json', report)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', required=True)
    parser.add_argument('--target-installer')
    parser.add_argument('--output', required=True)
    parser.add_argument('--keep-workspace', action='store_true')
    parser.add_argument('--legacy-installer')
    parser.add_argument('--playwright-root', default='validation/legacy-runner')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Somente Windows executa instaladores; importar/testar helpers é permitido em outros sistemas.')
    for path in filter(None, (args.installer, args.target_installer, args.legacy_installer)):
        installer_version(path)
        with Path(path).open('rb') as source:
            if source.read(2) != b'MZ':
                parser.error('Arquivo não parece um instalador Windows: '+path)
    if args.legacy_installer:
        run_legacy(args)
    else:
        if not args.target_installer:
            parser.error('Informe --target-installer para validar atualização nativa.')
        NativeValidation(args.installer, args.target_installer, args.output, args.keep_workspace).run()


if __name__ == '__main__':
    main()
