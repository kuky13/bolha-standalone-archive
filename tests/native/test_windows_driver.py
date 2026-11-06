# SPDX-License-Identifier: GPL-3.0-only
"""Servidor e limites do driver podem ser testados sem executar .exe."""
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from urllib.error import HTTPError
from http.client import IncompleteRead
from urllib.request import urlopen

import pytest
from scripts.test_windows_native import (Feed, NativeValidation, installer_version,
    legacy_allowed, read_json, test_environment as environment, validate_metrics, write_json)
import scripts.test_windows_native as driver


def test_registro_ignora_criacao_da_chave_compartilhada_mas_detecta_entrada_da_bolha(monkeypatch):
    from contextlib import nullcontext
    import sys
    state=dict(exists=False,bolha=None)
    def open_key(_root,location,*_args):
        if not location.endswith('Run') or not state['exists']:
            raise FileNotFoundError
        return nullcontext(location)
    def query(_key,name):
        assert name=='Bolha'
        if state['bolha'] is None:
            raise FileNotFoundError
        return state['bolha'],1
    registry=SimpleNamespace(OpenKey=open_key,QueryValueEx=query,HKEY_CURRENT_USER=1,
                             KEY_READ=1,KEY_WOW64_64KEY=2)
    monkeypatch.setitem(sys.modules,'winreg',registry)
    before=driver.registry_fingerprint()
    state['exists']=True
    assert driver.registry_fingerprint()==before
    state['bolha']='Bolha.exe'
    assert driver.registry_fingerprint()!=before


@pytest.mark.parametrize('exited',[True,False])
def test_consulta_do_processo_aguarda_a_saida_sem_ignorar_falha_de_permissao(monkeypatch,exited):
    from unittest.mock import Mock
    kernel = SimpleNamespace(
        OpenProcess=Mock(return_value=1),
        WaitForSingleObject=Mock(side_effect=[258,0 if exited else 258]),
        QueryFullProcessImageNameW=Mock(return_value=False),
        CloseHandle=Mock(),
    )
    monkeypatch.setattr(driver.ctypes,'WinDLL',lambda *_args,**_kwargs:kernel,raising=False)
    monkeypatch.setattr(driver.ctypes,'get_last_error',lambda:5,raising=False)
    monkeypatch.setattr(driver.ctypes,'WinError',lambda code:PermissionError(code,'Acesso negado'),raising=False)
    if exited:
        assert driver.process_alive(123,'Bolha.exe') is False
    else:
        with pytest.raises(PermissionError):
            driver.process_alive(123,'Bolha.exe')
    assert kernel.WaitForSingleObject.call_args_list[-1].args==(1,100)
    kernel.CloseHandle.assert_called_once_with(1)


def test_legacy_never_runs_on_notebook_and_needs_hosted_runner():
    hosted = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows')
    assert legacy_allowed(hosted, 'github-runner')
    assert not legacy_allowed(hosted, 'KUKYBOOK26')
    assert not legacy_allowed(dict(hosted, RUNNER_ENVIRONMENT='self-hosted'), 'other')
    assert not legacy_allowed({}, 'other')


def test_environment_always_isolates_install_data_and_drops_inherited_test_flags(tmp_path, monkeypatch):
    monkeypatch.setenv('BOLHA_TEST_FAIL_START', '0.3.1')
    monkeypatch.setenv('BOLHA_TEST_LEGACY_CACHE', 'real-cache')
    env = environment(tmp_path/'data', tmp_path/'app', tmp_path/'report.json', 'http://127.0.0.1:12345/')
    assert env['BOLHA_TEST'] == env['BOLHA_TEST_ALLOW_STOP'] == '1'
    assert Path(env['BOLHA_TEST_USER_DATA']) == tmp_path/'data'
    assert Path(env['BOLHA_TEST_INSTALL_DIR']) == tmp_path/'app'
    assert 'BOLHA_TEST_FAIL_START' not in env and 'BOLHA_TEST_LEGACY_CACHE' not in env


def test_feed_exact_metadata_checksum_interruption_and_no_path_escape(tmp_path):
    installer = tmp_path/'Bolha-Setup-0.3.1-x64.exe'
    content = b'MZ'+b'fixture'*20000
    installer.write_bytes(content)
    with Feed(installer) as feed:
        release = json.load(urlopen(feed.url+'release.json'))
        assert release['tag_name'] == 'v0.3.1'
        asset = release['assets'][0]
        assert asset['size'] == len(content)
        assert asset['browser_download_url'] == feed.url+installer.name
        assert urlopen(asset['browser_download_url']).read() == content
        assert hashlib.sha256(content).hexdigest().encode() in urlopen(feed.url+'SHA256SUMS.txt').read()
        assert b'sha512:' in urlopen(feed.url+'latest.yml').read()
        with pytest.raises(HTTPError): urlopen(feed.url+'../outside.txt')
        feed.mode = 'checksum'
        assert b'0'*64 in urlopen(feed.url+'SHA256SUMS.txt').read()
        feed.mode = 'interrupted'
        with pytest.raises(IncompleteRead): urlopen(feed.url+installer.name).read()
        assert feed.interrupted
        feed.mode = 'offline'
        with pytest.raises(HTTPError) as failure: urlopen(feed.url+'release.json')
        assert failure.value.code == 503


def test_names_and_atomic_report(tmp_path):
    assert installer_version('Bolha-Setup-0.3.1-x64.exe') == '0.3.1'
    with pytest.raises(ValueError): installer_version('setup.exe')
    with pytest.raises(ValueError): installer_version('Bolha-Setup-../1-x64.exe')
    path = tmp_path/'nested/report.json'
    write_json(path, {'local':'memória ♡'})
    assert read_json(path) == {'local':'memória ♡'}
    assert not path.with_name(path.name+'.tmp').exists()


def test_stale_or_base_metrics_never_validate_new_target_health():
    health = dict(version='0.3.1', pid=222, ready=True, neurons=470)
    current = dict(version='0.3.1', pid=222, healthy=True, neurons=470, frameCount=10, thinkCount=3)
    assert validate_metrics(current, health) is current
    for invalid in ({}, dict(current, version='0.3.0'), dict(current, pid=111),
                    dict(current, healthy=False), dict(current, frameCount=0)):
        with pytest.raises(AssertionError):
            validate_metrics(invalid, health)


def test_reused_output_removes_previous_runtime_report_before_launch(tmp_path):
    base = tmp_path/'Bolha-Setup-0.3.0-x64.exe'
    target = tmp_path/'Bolha-Setup-0.3.1-x64.exe'
    base.write_bytes(b'MZbase')
    target.write_bytes(b'MZtarget')
    output = tmp_path/'reused-output'
    write_json(output/'automatic-update-runtime.json', dict(version='0.3.1', pid=111, healthy=True))
    validation = NativeValidation(base, target, output)
    try:
        env = validation.environment('automatic-update')
        assert not Path(env['BOLHA_TEST_REPORT']).exists()
        assert read_json(env['BOLHA_TEST_REPORT']) is None
        with pytest.raises(AssertionError):
            validate_metrics(read_json(env['BOLHA_TEST_REPORT']) or {}, dict(version='0.3.1',pid=222,ready=True,neurons=470))
    finally:
        shutil.rmtree(validation.root)


def test_stop_rejects_base_report_when_target_never_wrote_metrics(tmp_path, monkeypatch):
    validation = object.__new__(NativeValidation)
    validation.data, validation.exe = tmp_path/'data', tmp_path/'app/Bolha.exe'
    validation.current_report = tmp_path/'automatic-update-runtime.json'
    validation.processes = []
    monkeypatch.setattr(driver, 'process_alive', lambda *_: False)
    write_json(validation.current_report, dict(version='0.3.0', pid=111, healthy=True,
               neurons=470, frameCount=90, thinkCount=20))
    target_health = dict(version='0.3.1', pid=222, ready=True, neurons=470)
    with pytest.raises(AssertionError, match='outra versão'):
        validation.stop(target_health)
    validation.current_report.unlink()
    with pytest.raises(AssertionError):
        validation.stop(target_health)


def legacy_fixture(tmp_path):
    data, install = tmp_path/'bolha', tmp_path/'bolha-legacy-validation-test'/'app'
    data.mkdir();install.mkdir(parents=True)
    token = 'a'*32
    write_json(install.parent/'validation-owner.json', dict(token=token))
    write_json(data/'.bolha-legacy-validation.json', dict(token=token, createdBy='bolha-legacy-validation',
               data=str(data), install=str(install)))
    (data/'learning.json').write_text('preserve learned state', encoding='utf-8')
    (install/'Bolha.exe').write_bytes(b'MZnative')
    (install/'Uninstall Bolha.exe').write_bytes(b'MZuninstall')
    (install/'bolha-native-installation.flag').write_text('bolha-native:solutions.kuky.bolha', encoding='utf-8')
    write_json(install/'installed-files.json', dict(appId='solutions.kuky.bolha', version='0.3.0',
               files={'Bolha.exe': hashlib.sha256(b'MZnative').hexdigest()}))
    report = dict(health=dict(version='0.3.0',pid=123,ready=True,neurons=470),
                  metrics=dict(version='0.3.0',pid=123,healthy=True,neurons=470,frameCount=10,thinkCount=2))
    return data, install, token, report


def test_legacy_owner_rejects_wrong_nonce_foreign_path_and_accepts_own_uninstall(tmp_path):
    data, install, token, _ = legacy_fixture(tmp_path)
    assert driver.verify_legacy_owner(data,install,token)['token'] == token
    with pytest.raises(ValueError,match='ownership'):
        driver.verify_legacy_owner(data,install,'b'*32)
    with pytest.raises(ValueError,match='Caminhos'):
        driver.verify_legacy_owner(data,tmp_path/'foreign'/'app',token)
    shutil.rmtree(install)
    assert driver.verify_legacy_owner(data,install,token)['token'] == token


def test_legacy_owner_rejects_links_in_profile_or_workspace(tmp_path):
    data, install, token, _ = legacy_fixture(tmp_path)
    sentinel = tmp_path/'foreign-document.txt';sentinel.write_text('keep')
    for base in (data, install.parent):
        link = base/'linked-document'
        try:link.symlink_to(sentinel)
        except OSError:pytest.skip('symlinks indisponíveis')
        try:
            with pytest.raises(ValueError,match='Atalho'):
                driver.verify_legacy_owner(data,install,token)
        finally:link.unlink()
    assert sentinel.read_text() == 'keep'


def test_legacy_refuses_existing_profile_or_registration_before_install(tmp_path,monkeypatch):
    monkeypatch.setattr(driver,'legacy_allowed',lambda:True)
    monkeypatch.setenv('APPDATA',str(tmp_path))
    args = SimpleNamespace(output=tmp_path/'output')
    (tmp_path/'bolha').mkdir()
    with pytest.raises(FileExistsError,match='perfil'):
        driver.run_legacy(args)
    (tmp_path/'bolha').rmdir()
    monkeypatch.setattr(driver,'legacy_registration_absent',lambda:False)
    with pytest.raises(FileExistsError,match='registrada'):
        driver.run_legacy(args)
    assert not list(tmp_path.glob('bolha-legacy-validation-*'))


@pytest.mark.parametrize('failure',['not_hosted','active_process','wrong_registration'])
def test_legacy_cleanup_failure_preserves_profile_and_never_runs_uninstaller(tmp_path,monkeypatch,failure):
    data,install,token,report = legacy_fixture(tmp_path)
    monkeypatch.setattr(driver,'legacy_allowed',lambda:failure!='not_hosted')
    monkeypatch.setattr(driver,'process_alive',lambda *_:failure=='active_process')
    def immediate_wait(description,predicate,timeout):
        if not predicate():raise TimeoutError(description)
    monkeypatch.setattr(driver,'wait_for',immediate_wait)
    def wrong_registration(*_):raise ValueError('registro diferente')
    monkeypatch.setattr(driver,'legacy_registration',wrong_registration)
    monkeypatch.setattr(driver.subprocess,'run',lambda *_args,**_kwargs:pytest.fail('uninstaller não deveria executar'))
    with pytest.raises((PermissionError,TimeoutError,ValueError)):
        driver.cleanup_legacy_runner(data,install,token,'0.3.0',tmp_path/'output',report)
    assert (data/'learning.json').read_text() == 'preserve learned state'
    assert (install/'Bolha.exe').exists()


def test_legacy_cleanup_waits_for_exit_archives_then_uninstalls_only_owned_install(tmp_path,monkeypatch):
    data,install,token,report = legacy_fixture(tmp_path)
    monkeypatch.setattr(driver,'legacy_allowed',lambda:True)
    monkeypatch.setattr(driver,'process_alive',lambda *_:False)
    monkeypatch.setattr(driver,'legacy_registration',lambda *_:dict(guid='expected',install=str(install),version='0.3.0'))
    monkeypatch.setattr(driver,'legacy_registration_absent',lambda:True)
    calls=[]
    def uninstall(args,**kwargs):
        assert args == [str(install/'Uninstall Bolha.exe'),'/S']
        assert kwargs == dict(check=True,timeout=90)
        assert (tmp_path/'output'/('evidence-'+token[:8])/'profile'/'learning.json').read_text() == 'preserve learned state'
        calls.append(args)
        shutil.rmtree(install)
    monkeypatch.setattr(driver.subprocess,'run',uninstall)
    result=driver.cleanup_legacy_runner(data,install,token,'0.3.0',tmp_path/'output',report)
    assert len(calls)==1 and result['nativeProcessExited'] and result['registrationRemoved']
    assert not data.exists() and not install.parent.exists()
    assert Path(result['evidence']).is_dir()
