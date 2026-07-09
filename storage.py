"""Хранилище состояний - один словарь на весь процесс"""

_data = {}

def get(key, default=None):
    return _data.get(key, default)

def set(key, value):
    _data[key] = value

def delete(key):
    _data.pop(key, None)
