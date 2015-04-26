# Blorp-python
Python client implementation for [Blorp](https://github.com/jrdh/blorp).
Uses async-redis, redis and Python's asyncio module.

## Todo
- implement instance switching (i.e. when a python instance shuts down, move the messages to another one if there is one)
- tidy (~)
- tests

## To think about...
- work out how to do cope with load balancing (almost there...)
