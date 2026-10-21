"""Transport worker. Vendor stdout is routed to stderr, away from the protocol."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib
import json
import os
import sys
import threading

from ..transport.protocol import TransportRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--factory', required=True)
    args = parser.parse_args()
    control = os.fdopen(os.dup(sys.stdout.fileno()), 'w', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    lock = threading.Lock()

    def write(value):
        with lock:
            control.write(json.dumps(value) + '\n')

    def event(value):
        data = asdict(value)
        data['received_at'] = value.received_at.isoformat()
        write({'event': data})

    transport = None
    try:
        for line in sys.stdin:
            request = json.loads(line)
            try:
                method = request['method']
                if method == 'connect':
                    module, name = args.factory.split(':', 1)
                    transport = getattr(importlib.import_module(module), name)()
                    transport.connect([TransportRequest(**b) for b in request['bindings']], event)
                    result = None
                elif method == 'ready':
                    result = transport.ready(request['bindings'])
                elif method == 'execute':
                    result = asdict(transport.execute(TransportRequest(**request['request'])))
                else:
                    raise ValueError('Unknown Host operation')
                write({'id': request['id'], 'result': result})
            except Exception as exc:
                write({'id': request['id'], 'error': str(exc)})
    except KeyboardInterrupt:
        pass
    finally:
        if transport is not None:
            transport.close()
        control.close()


if __name__ == '__main__':
    main()
