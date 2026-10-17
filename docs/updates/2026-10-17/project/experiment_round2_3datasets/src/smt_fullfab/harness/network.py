"""Frozen loopback-only experiment routing; no credentials enter evidence."""
from pathlib import Path
import re
import socket
import subprocess
import time
from .contracts import require, sha_bytes


def process_identity(pid):
    require(type(pid) is int and pid > 0, 'network_identity', 'Invalid process identity')
    result = subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart=','-o','comm='],
                            capture_output=True, text=True, timeout=5)
    require(result.returncode == 0 and result.stdout.strip(), 'network_unavailable', 'The bound proxy process is not alive')
    return result.stdout.strip()


def validate_binding(reference, *, live=False):
    if reference.get('mode') == 'user_managed_host_network':
        from .user_managed_network import validate_reference
        return validate_reference(reference)
    if reference.get('mode') == 'system_tun':
        from .network_tun import validate_binding as validate_tun
        return validate_tun(reference, live=live)
    from .experiment import checked_file
    match = re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})', reference['url'])
    require(match is not None and int(match.group(1)) <= 65535, 'network_binding', 'Explicit loopback HTTP proxy required')
    value = checked_file(reference['binding'])
    require(value['schema'] == 'harness-scoped-proxy-v1' and value['proxy_url'] == reference['url'] and
            value['node_hash'] == '4340036fce26' and value['proxy_type'] == 'vless' and
            value['DNS_source'] == 'existing_Clash_DNS' and value['allow_lan'] is False and value['tun'] is False and
            value['credentials_persisted'] is False and value['global_settings_changed'] is False,
            'network_binding', 'Route differs from the isolated verified configuration')
    require(value['lease_end_epoch'] > value['started_epoch'] and type(value['pid']) is int and
            all(len(value[k]) == 64 for k in ('node_config_sha256','dns_config_sha256','binary_sha256','launcher_sha256')),
            'network_binding', 'Frozen process/configuration evidence required')
    require(len(value['public_https_checks']) == 8 and all(x['returncode'] == 0 and x['http_status'] == '200' for x in value['public_https_checks']),
            'network_preflight', 'Eight successful non-model HTTPS checks required')
    if live:
        require(time.time() < value['lease_end_epoch'] and process_identity(value['pid']) == value['process_identity'],
                'network_unavailable', 'Bound proxy ended, changed identity, or expired; no fallback')
        require(sha_bytes(Path(value['binary']).read_bytes()) == value['binary_sha256'], 'network_identity', 'Proxy binary changed')
        try:
            with socket.create_connection(('127.0.0.1', int(match.group(1))), timeout=1):
                pass
        except OSError:
            require(False, 'network_unavailable', 'Bound listener unavailable; no model attempt is reserved')
    return value


def for_admission(admission, *, live=False, attempt=None, run_id=None):
    from .experiment import registration
    reg = registration(admission)
    if 'transport_proxy' not in reg:
        return None
    from .user_managed_network import reference as network_reference
    reference = network_reference(reg, admission, attempt=attempt, run_id=run_id)
    validate_binding(reference, live=live)
    return reference


def apply_environment(environment, reference):
    environment = dict(environment)
    if reference and reference.get('mode') == 'user_managed_host_network':
        validate_binding(reference)
        return environment
    if reference:
        for key in list(environment):
            if key.upper() in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'):
                environment.pop(key)
    if reference and reference.get('mode') == 'system_tun':
        environment['NO_PROXY'] = environment['no_proxy'] = '*'
        return environment
    for key in ('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY'):
        environment[key] = reference['url'] if reference else 'http://127.0.0.1:7897'
    return environment
