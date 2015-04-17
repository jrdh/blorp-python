import asyncio
from datetime import datetime

import asyncio_redis
import anyjson as json
import blorp


class BaseWebsocketHandler:
    DISCONNECT_MESSAGE = None

    def __init__(self, websocket_id, app):
        self.websocket_id = websocket_id
        self.app = app
        self.message_queue = asyncio.Queue()
        self.go = True
        # cache for current session
        self.session = None

    @asyncio.coroutine
    def on_connection(self):
        while self.go:
            message = yield from self.message_queue.get()
            if message == BaseWebsocketHandler.DISCONNECT_MESSAGE:
                break
            yield from self.call_handler(*message)

    @asyncio.coroutine
    def on_disconnection(self):
        self.go = False
        yield from self.message_queue.put(BaseWebsocketHandler.DISCONNECT_MESSAGE)

    @asyncio.coroutine
    def call_handler(self, message_handler, data):
        # ensure there is a session for this websocket and cache it
        yield from self.get_session()
        response = yield from message_handler(self, data)
        if response:
            if not isinstance(response, blorp.Response):
                response = blorp.Response(response)
            yield from response.send(self, message_handler.return_event)

    @asyncio.coroutine
    def send_message_back(self, event, message):
        yield from self.send_message(self.websocket_id, event, message)

    @asyncio.coroutine
    def send_message_to_all(self, event, message):
        yield from self.send_message(blorp.ALL_TARGET, event, message)

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


class BaseWebsocketHandlerFactory:

    def __init__(self, app):
        self.app = app

    @asyncio.coroutine
    def get_new_websocket_handler(self, websocket_id):
        websocket_handler = self.app.handler_cls(websocket_id, self.app)
        asyncio.async(websocket_handler.on_connection())
        return websocket_handler


class BaseWebsocketHandlerRouter:

    def __init__(self, app):
        self.app = app
        self.websocket_handlers = {}
        self.async_sender = None

    @asyncio.coroutine
    def add_websocket_handler(self, websocket_id):
        yield from self.app.get_session(websocket_id, create=True)
        self.websocket_handlers[websocket_id] = yield from self.app.factory.get_new_websocket_handler(websocket_id)

    @asyncio.coroutine
    def remove_websocket_handler(self, websocket_id):
        if websocket_id in self.websocket_handlers:
            yield from self.websocket_handlers[websocket_id].on_disconnection()
            yield from self.app.delete_session(websocket_id)
            del self.websocket_handlers[websocket_id]

    @asyncio.coroutine
    def route(self, websocket_id, event, data):
        for regex, on_message_function in self.app.message_handlers:
            if regex.match(event) and websocket_id in self.websocket_handlers:
                websocket_handler = self.websocket_handlers[websocket_id]
                if on_message_function.in_order:
                    # add to message queue for that websocket responder
                    yield from websocket_handler.message_queue.put((on_message_function, data))
                else:
                    # run responder immediately
                    asyncio.async(websocket_handler.call_handler(on_message_function, data))
                break


class WebsocketReceiver:

    def __init__(self, app):
        self.app = app
        self.run = True

    @asyncio.coroutine
    def message_loop(self):
        message_receiver = yield from asyncio_redis.Connection.create(host=self.app.host, port=self.app.port)

        message_handlers = {
            'connection': lambda m: self.app.router.add_websocket_handler(m['websocketId']),
            'disconnection': lambda m: self.app.router.remove_websocket_handler(m['websocketId']),
            'message': lambda m: self.app.router.route(m['websocketId'], m['event'], m['data'])
        }

        while self.run:
            raw_message = yield from message_receiver.blpop([self.app.keys['queues']])
            message = json.loads(raw_message.value)
            yield from message_handlers[message['type']](message)

        message_receiver.close()
