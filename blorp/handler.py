import asyncio
from datetime import datetime
from functools import partial

import asyncio_redis
import anyjson as json
import blorp


class QueueHandler:

    def __init__(self, app, queue_key):
        self.app = app
        self.queue_key = queue_key
        self.run = True
        self.blpop_task = None
        self.redis = None
        self.stopped = False

    @asyncio.coroutine
    def listen(self):
        self.redis = yield from asyncio_redis.Connection.create(host=self.app.host, port=self.app.port,
                                                                db=self.app.database)
        while self.run:
            self.blpop_task = asyncio.async(self.get_next_message())
            message = yield from asyncio.wait_for(self.blpop_task, timeout=None)
            if message:
                yield from self.handle_message(message.value)
            else:
                break

        self.redis.close()
        return self.stopped

    @asyncio.coroutine
    def get_next_message(self):
        try:
            return (yield from self.redis.blpop([self.queue_key]))
        except asyncio.CancelledError as _e:
            return None

    @asyncio.coroutine
    def stop(self):
        self.run = False
        if self.blpop_task:
            self.blpop_task.cancel()
        self.stopped = True

    @asyncio.coroutine
    def handle_message(self, message):
        pass


class BaseWebsocketHandler(QueueHandler):

    def __init__(self, app, websocket_id):
        super().__init__(app, app.keys['messages'].format(websocket_id))
        self.websocket_id = websocket_id
        self.session = None
        self.types = {'disconnection': self.on_disconnection, 'message': self.on_message}

    @asyncio.coroutine
    def handle_message(self, message):
        parsed_message = json.loads(message)
        yield from self.types[parsed_message['type']](**parsed_message['message'])

    @asyncio.coroutine
    def on_disconnection(self):
        yield from self.delete_session()
        self.run = False
        self.stopped = False

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


class WebsocketControlReceiver(QueueHandler):

    def __init__(self, app):
        super().__init__(app, app.keys['control'])
        self.handlers = {}

    def create_handler(self, websocket_id):
        return self.app.handler_cls(self.app, websocket_id)

    def remove_handler(self, websocket_id, listen_task):
        if not listen_task.result():
            del self.handlers[websocket_id]

    def create_switch_message(self, websocket_id):
        return json.dumps({'action': 'switch', 'websocketId': websocket_id, 'from': str(self.app.instance_id)})

    @asyncio.coroutine
    def listen(self):
        yield from self.handle_message('{"action": "connection", "websocketId": "lemonade2"}')

        # block on the super listening function, once this completes it means we've been asked to stop
        yield from super().listen()

        # first stop all the running handlers
        tasks = []
        for websocket_id, (handler, task) in self.handlers.items():
            tasks.append(task)
            yield from handler.stop()

        # then wait for them all to stop
        if tasks:
            yield from asyncio.wait(tasks)

        # then send out switch messages for all remaining handlers (disconnected handlers remove themselves)
        if self.handlers:
            control_sender = yield from asyncio_redis.Connection.create(host=self.app.host, port=self.app.port,
                                                                        db=self.app.database)
            
            # any handlers left in the self.handlers dict need to be switched to another instance
            switch_messages = [self.create_switch_message(websocket_id) for websocket_id in self.handlers.keys()]
            yield from control_sender.rpush(self.app.keys['control'], switch_messages)
            control_sender.close()

    @asyncio.coroutine
    def handle_message(self, message):
        parsed_message = json.loads(message)
        action = parsed_message['action']
        if action == 'connection' or action == 'switch':
            websocket_id = parsed_message['websocketId']
            handler = self.create_handler(websocket_id)
            # a task is automatically scheduled when it is created
            listen_task = asyncio.async(handler.listen(), loop=self.app.event_loop)
            self.handlers[websocket_id] = (handler, listen_task)
            # add callback to task so that it can clean itself up on disconnect or stop
            listen_task.add_done_callback(partial(self.remove_handler, websocket_id))
