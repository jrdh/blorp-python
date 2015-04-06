import asyncio
from functools import wraps

import re
import anyjson as json


_handler_counter = 0


def on(event_regex, re_flags=0, ordered=True, order=None, parse_json=False):
    global _handler_counter
    _handler_counter += 1

    def wrap(f):
        if parse_json:
            f = json_message(f)
        f = asyncio.coroutine(f)

        @asyncio.coroutine
        @wraps(f)
        def wrapped_f(*args):
            return (yield from f(*args))
        wrapped_f.message_handler = True
        wrapped_f.event_regex = re.compile(event_regex, re_flags)
        f.in_order = ordered
        wrapped_f.original = f
        f.order = order if order else _handler_counter
        return wrapped_f
    return wrap


def json_message(on_message_function):
    @wraps(on_message_function)
    def _wrapped_on_message_function(responder_instance, message):
        return on_message_function(responder_instance, json.loads(message))
    return _wrapped_on_message_function


def create_message(to, event, data):
    return json.dumps({'id': to, 'event': event, 'data': data})
