import asyncio
from datetime import datetime
import threading
import inspect
import uuid

import asyncio_redis
import anyjson as json
import blorp
import redis


class BlorpApp:

    def __init__(self, name, host='localhost', port=6379, database=0, pool_size=10, session_ttl=1800,
                 handler_cls=blorp.BaseWebsocketHandler):
        self.name = name
        self.host = host
        self.port = port
        self.database = database
        self.pool_size = pool_size
        self.handler_cls = handler_cls
        self.session_ttl = session_ttl
        self.message_handlers = []
        self.event_loop = None
        self.thread = None
        self.async_pool = None
        self.sync_pool = None
        self.instance_id = None
        self.key_prefix = 'blorp:{0}:{1}'.format(self.name, '{0}')
        self.keys = {
            'session': self.key_prefix.format('sessions:{0}'),
            'out': self.key_prefix.format('out'),
            'control': self.key_prefix.format('control'),
            'messages': self.key_prefix.format('messages:{0}'),
            'instances': self.key_prefix.format('instances')
        }
        self.receiver = blorp.WebsocketControlReceiver(self)

    def init_message_handlers(self):
        predicate = lambda m: inspect.isfunction(m) and hasattr(m, 'message_handler') and m.message_handler
        self.message_handlers = sorted(((func.event_regex, func) for _, func in
                                        inspect.getmembers(self.handler_cls, predicate)), key=lambda t: t[1].order)

    @asyncio.coroutine
    def init_async_pool(self):
        self.async_pool = yield from asyncio_redis.Pool.create(host=self.host, port=self.port, poolsize=self.pool_size,
                                                               db=self.database)

    def init_sync_pool(self):
        self.sync_pool = redis.StrictRedis(host=self.host, port=self.port, db=self.database)

    def register_instance(self):
        attempts = 0
        while attempts < 3:
            potential_instance_id = uuid.uuid4()
            if self.sync_pool.sadd(self.keys['instances'], potential_instance_id):
                self.instance_id = potential_instance_id
                return
            attempts += 1

    def start(self):
        self.init_message_handlers()
        self.init_sync_pool()

        self.register_instance()

        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)

        self.event_loop.run_until_complete(self.init_async_pool())
        self.event_loop.run_until_complete(self.receiver.listen())

        self.sync_pool.srem(self.keys['instances'], self.instance_id)
        self.async_pool.close()
        self.event_loop.stop()
        self.event_loop.close()

    def start_in_new_thread(self, daemon=False, **kwargs):
        self.thread = threading.Thread(target=self.start, kwargs=kwargs, daemon=daemon)
        self.thread.start()

    def stop(self):
        self.event_loop.call_soon_threadsafe(asyncio.async, self.receiver.stop())

    def send_sync(self, to, event, data):
        self.sync_pool.rpush(self.keys['out'], blorp.create_message(to, event, data))

    def send_sync_to_all(self, event, data):
        self.send_sync(blorp.Target.ALL, event, data)

    @asyncio.coroutine
    def send_async(self, to, event, data):
        yield from self.async_pool.rpush(self.keys['out'], [blorp.create_message(to, event, data)])

    @asyncio.coroutine
    def send_async_to_all(self, event, data):
        yield from self.send_async(blorp.Target.ALL, event, data)

    @asyncio.coroutine
    def save_session(self, websocket_id, session):
        yield from self.async_pool.set(self.keys['session'].format(websocket_id), json.dumps(session),
                                       expire=self.session_ttl)

    @asyncio.coroutine
    def create_new_session(self, websocket_id):
        session = {'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        yield from self.save_session(websocket_id, session)
        return session

    @asyncio.coroutine
    def delete_session(self, websocket_id):
        yield from self.async_pool.delete([self.keys['session'].format(websocket_id)])

    @asyncio.coroutine
    def touch_session(self, websocket_id):
        yield from self.async_pool.expire(self.keys['session'].format(websocket_id), self.session_ttl)

    @asyncio.coroutine
    def get_session(self, websocket_id, create=True):
        session = yield from self.async_pool.get(self.keys['session'].format(websocket_id))
        if session:
            yield from self.touch_session(websocket_id)
            return json.loads(session)
        elif create:
            return (yield from self.create_new_session(websocket_id))
        return None

    @asyncio.coroutine
    def call_blocking(self, f, *args):
        return (yield from self.event_loop.run_in_executor(None, f, *args))
