import asyncio
from enum import Enum
from functools import wraps

import re
import anyjson as json


_handler_counter = 0


def on(event_regex, re_flags=0, order=None, return_event=None):
    global _handler_counter
    _handler_counter += 1

    def wrap(f):
        f = asyncio.coroutine(f)

        @asyncio.coroutine
        @wraps(f)
        def wrapped_f(*args):
            return (yield from f(*args))
        wrapped_f.message_handler = True
        wrapped_f.event_regex = re.compile(event_regex, re_flags)
        wrapped_f.return_event = return_event
        wrapped_f.original = f
        wrapped_f.order = order if order else _handler_counter
        return wrapped_f
    return wrap


def create_message(to, event, data):
    return json.dumps({'id': None if to is Target.ALL else to, 'event': event, 'data': data})


class Target(Enum):
    ALL = 0


class Response:

    def __init__(self, message, target=None, event=None):
        self.message = message
        self.target = target
        self.event = event

    @asyncio.coroutine
    def send(self, handler, return_event):
        yield from handler.send_message(self.target if self.target is not None else handler.websocket_id,
                                        self.event if self.event is not None else return_event,
                                        self.message)
