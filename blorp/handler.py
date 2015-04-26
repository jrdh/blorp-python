import asyncio
from datetime import datetime
from functools import partial

import asyncio_redis
import anyjson as json
import blorp


class BaseWebsocketHandler:

    def __init__(self, websocket_id, app):
        self.websocket_id = websocket_id
        self.app = app
        self.queue_key = self.app.keys['messages'].format(self.websocket_id)
        self.disconnected = False
        # cache for current session
        self.session = None
        self.redis = None
        self.types = {'disconnection': self.on_disconnection, 'message': self.on_message}

    @asyncio.coroutine
    def listen(self):
        self.redis = yield from asyncio_redis.Connection.create(host=self.app.host, port=self.app.port,
                                                                db=self.app.database)
        while not self.disconnected:
            message = yield from self.redis.blpop([self.queue_key])
            parsed_message = json.loads(message.value)
            yield from self.types[parsed_message['type']](**parsed_message['message'])

    @asyncio.coroutine
    def on_disconnection(self):
        yield from self.delete_session()
        self.disconnected = True

    @asyncio.coroutine
    def on_message(self, event=None, data=None):
        if event:
            for regex, on_message_function in self.app.message_handlers:
                if regex.match(event):
                    # ensure there is a session for this websocket and cache it
                    yield from self.get_session()
                    response = yield from on_message_function(self, data)
                    if response:
                        if not isinstance(response, blorp.Response):
                            response = blorp.Response(response)
                        yield from response.send(self, on_message_function.return_event)
                    break

    @asyncio.coroutine
    def send_message_back(self, event, message):
        yield from self.send_message(self.websocket_id, event, message)

    @asyncio.coroutine
    def send_message_to_all(self, event, message):
        yield from self.send_message(blorp.Target.ALL, event, message)

    @asyncio.coroutine
    def send_message(self, target, event, message):
        yield from self.app.send_async(target, event, message)

    @asyncio.coroutine
    def get_session(self, update_cache=True):
        session = yield from self.app.get_session(self.websocket_id)
        if update_cache:
            self.session = session
        return session

    @asyncio.coroutine
    def save_session(self, session=None, update_cache=True):
        if update_cache and session:
            self.session = session
        yield from self.app.save_session(self.websocket_id, self.session)

    @asyncio.coroutine
    def create_new_session(self, update_cache=True):
        session = {'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        yield from self.save_session(session=session, update_cache=update_cache)
        return session

    @asyncio.coroutine
    def delete_session(self, update_cache=True):
        yield from self.app.delete_session(self.websocket_id)
        if update_cache:
            self.session = None

    @asyncio.coroutine
    def touch_session(self):
        yield from self.app.touch_session(self.websocket_id)

    @asyncio.coroutine
    def call_blocking(self, f, *args):
        return (yield from self.app.call_blocking(f, *args))


class WebsocketReceiver:

    def __init__(self, app):
        self.app = app
        self.run = True
        self.handlers = {}

    def create_handler(self, websocket_id):
        return self.app.handler_cls(websocket_id, self.app)

    def remove_handler(self, websocket_id, _listen_task):
        del self.handlers[websocket_id]

    @asyncio.coroutine
    def message_loop(self):
        message_receiver = yield from asyncio_redis.Connection.create(host=self.app.host, port=self.app.port,
                                                                      db=self.app.database)

        while self.run:
            raw_message = yield from message_receiver.blpop([self.app.keys['control']])
            message = json.loads(raw_message.value)
            
            action = message['action']
            if action == 'connection':
                websocket_id = message['websocketId']
                handler = self.create_handler(websocket_id)
                # a task is automatically scheduled when it is created
                listen_task = asyncio.async(handler.listen(), loop=self.app.event_loop)
                self.handlers[websocket_id] = (handler, listen_task)
                listen_task.add_done_callback(partial(self.remove_handler, websocket_id))
            elif action == 'switch':
                pass

        message_receiver.close()
