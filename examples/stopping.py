import asyncio
import blorp


class WebsocketHandler(blorp.BaseWebsocketHandler):

    def __init__(self, websocket_id, app):
        super().__init__(websocket_id, app)

    @asyncio.coroutine
    def handle_message(self, message):
        print("got a message {0}".format(message))


if __name__ == '__main__':
    blorp_app = blorp.BlorpApp('basic', handler_cls=WebsocketHandler)
    blorp_app.start_in_new_thread()
    while True:
        text = input("Stop to stop: ")
        if text == "stop":
            break
    blorp_app.stop()

    # TODO: fix this (all the clean up code is in start, so if we get a keyboard interrupt we don't get a cleanup):
    # blorp_app2 = blorp.BlorpApp('basic', handler_cls=WebsocketHandler)
    # try:
    #     blorp_app2.start()
    # except KeyboardInterrupt as _e:
    #     blorp_app2.stop()
