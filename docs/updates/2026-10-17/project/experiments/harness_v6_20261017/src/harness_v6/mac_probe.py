"""Mac-only local scripted Responses endpoint; NEVER connects to a model.

Usage: python -m harness_v6.mac_probe --fixtures /absolute/responses.json
Each fixture is {status, content_type, body}; body is exact JSON or SSE bytes
encoded as a JSON string. Captured request bodies go to a new exclusive JSONL.
Pinned Codex wire fixtures must be prepared/verified on the Mac. Launch Codex
separately with its provider URL pointed at the printed loopback address.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .contracts import strict_json, encode


def create_server(fixtures, log, *, port=0):
    responses=list(fixtures) if not callable(fixtures) else None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
            log.write(encode({'path':self.path,'body':raw.decode()})+b'\n');log.flush()
            if responses is not None and not responses:
                self.send_error(409,'No scripted response remains');return
            try:
                row=fixtures(strict_json(raw)) if callable(fixtures) else responses.pop(0)
            except (ValueError, KeyError) as exc:
                self.send_error(422, str(exc)); return
            body=row['body'].encode()
            self.send_response(row.get('status',200))
            self.send_header('Content-Type',row['content_type'])
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',port),Handler)
    return server


def serve(fixtures, log, *, port=0):
    server = create_server(fixtures, log, port=port)
    print(f'http://127.0.0.1:{server.server_port}/v1',flush=True)
    try:server.serve_forever()
    finally:server.server_close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--fixtures',required=True);p.add_argument('--log',required=True);p.add_argument('--port',type=int,default=0)
    a=p.parse_args()
    with Path(a.log).open('xb') as log:serve(strict_json(Path(a.fixtures).read_bytes()),log,port=a.port)

if __name__=='__main__':main()
