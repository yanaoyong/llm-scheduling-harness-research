"""Explicit system-TUN route, pinned to the user's tested current selector."""
import hashlib
import http.client
from pathlib import Path
import socket
import subprocess

from .contracts import digest, require, strict_json


def configuration_hashes(route):
    """Hash node/DNS configuration in memory; never emit credentials or hosts."""
    source = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml'
    program = 'require "yaml"; require "json"; puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), permitted_classes: [], permitted_symbols: [], aliases: true))'
    result = subprocess.run(['/usr/bin/ruby', '-e', program, str(source)], capture_output=True, timeout=10)
    require(result.returncode == 0, 'network_unavailable', 'Cannot inspect current node configuration')
    value = strict_json(result.stdout)
    nodes = [node for node in value['proxies'] if hashlib.sha256(node['name'].encode()).hexdigest()[:12] == route['chain'][-1]['hash']]
    require(len(nodes) == 1, 'network_binding', 'Selected node is missing or ambiguous')
    return {'node_config_sha256': digest(nodes[0]), 'dns_config_sha256': digest(value['dns'])}


def current_route():
    # Authentication stays in memory and is used only for the local controller.
    path = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml'
    options = {}
    for line in path.read_text().splitlines():
        if line and not line[0].isspace() and ':' in line:
            key, value = line.split(':', 1)
            if key in ('secret', 'external-controller-unix'):
                options[key] = value.strip().strip('\"\'')
    class Local(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect(options['external-controller-unix'])
    def get(path):
        connection = Local('localhost')
        try:
            connection.request('GET', path, headers={'Authorization': 'Bearer ' + options['secret']})
            response = connection.getresponse()
            require(response.status == 200, 'network_unavailable', 'Local route controller unavailable')
            return strict_json(response.read())
        finally:
            connection.close()
    proxies, config = get('/proxies')['proxies'], get('/configs')
    name, chain = 'GLOBAL', []
    while name in proxies:
        item = proxies[name]
        chain.append({'hash': hashlib.sha256(name.encode()).hexdigest()[:12], 'type': item['type']})
        name = item.get('now', '')
        require(len(chain) < 20, 'network_binding', 'Cyclic route selector')
    return {'mode': config['mode'], 'chain': chain, 'proxy_url': 'http://127.0.0.1:7897',
            'tun_enabled': config.get('tun', {}).get('enable'), 'tun_stack': config.get('tun', {}).get('stack'),
            'tun_auto_route': config.get('tun', {}).get('auto-route'), 'mixed_port': config.get('mixed-port')}


def validate_binding(reference, *, live=False):
    from .experiment import checked_file
    value = checked_file(reference['binding'])
    require(reference['mode'] == 'system_tun' and value['schema'] == 'harness-system-TUN-binding-v1'
            and value['explicit_proxy'] is None and value['NO_PROXY'] == '*'
            and value['credentials_persisted'] is False and value['global_settings_changed'] is False,
            'network_binding', 'Expected tested TUN-only routing with no explicit proxy')
    route = value['route']
    require(route['mode'] == 'global' and route['tun_enabled'] is True and route['tun_auto_route'] is True
            and route['tun_stack'] == 'gVisor' and route['mixed_port'] == 7897
            and route['chain'] == [{'hash': 'e7440dd384f1', 'type': 'Selector'}, {'hash': '8530e8302f5e', 'type': 'AnyTLS'}],
            'network_binding', 'Route differs from the three completed stream checks')
    require(set(value['configuration_hashes']) == {'node_config_sha256', 'dns_config_sha256'}
            and all(isinstance(h, str) and len(h) == 64 for h in value['configuration_hashes'].values()),
            'network_binding', 'Frozen node and DNS configuration hashes required')
    if live:
        require(current_route() == route, 'network_unavailable', 'TUN or selected route changed; no model request admitted')
        require(configuration_hashes(route) == value['configuration_hashes'],
                'network_unavailable', 'Selected node or DNS configuration changed; no model request admitted')
    return value
