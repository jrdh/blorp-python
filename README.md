# blorp
A 'bridge' that allows socket.io websocket connections to be used from (currently) Python via redis and node.js.
Uses redis and Python's asyncio module.

## Todo
- implement instance switching (i.e. when a client instance shuts down, move the messages to another one if there is one)
- implement dynamic namespaces (using redis keyspace notifcations?)
- tidy (~)
- tests
- investigate using hashes in redis
- Javascript client library (i.e. for the browser)


## To think about...
- work out how to do cope with load balancing (almost there...)
