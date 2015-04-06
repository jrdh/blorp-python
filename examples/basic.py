import asyncio
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

import blorp


class WebsocketHandler(blorp.BaseWebsocketHandler):

    def __init__(self, websocket_id, app):
        super().__init__(websocket_id, app)

    @blorp.on('json', ordered=False, parse_json=True)
    def on_json(self, message):
        return 'something', {'orig': message, 'new': 'hello {0}!'.format(self.websocket_id)}

    @blorp.on('string')
    def on_string(self, message):
        yield from asyncio.sleep(5)
        self.session['string_message_sent'] = True
        yield from self.app.save_session(self.websocket_id, self.session)
        return 'something', 'Got "{0}" from you!'.format(message)

    @blorp.on('.*')
    def on_everything_else(self, message):
        return blorp.ALL_TARGET, 'something', '{0} sent a message to everyone: "{1}"'.format(self.websocket_id, message)


if __name__ == '__main__':
    blorp_app = blorp.BlorpApp('basic', handler_cls=WebsocketHandler)
    blorp_app.start_in_new_thread()

    httpd = HTTPServer(('localhost', 8000), SimpleHTTPRequestHandler)
    try:
        t = threading.Thread(target=httpd.serve_forever)
        t.start()
        while True:
            blorp_app.send_sync_to_all('something', input("Type something to say to the nice websockets: "))
    except KeyboardInterrupt as _:
        httpd.shutdown()
        httpd.server_close()
        blorp_app.stop()
        exit(0)
