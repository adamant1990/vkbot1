"""Простое хранилище состояний вместо CtxStorage"""

class SimpleStorage:
    def __init__(self):
        self._data = {}
    
    def get(self, key, default=None):
        return self._data.get(key, default)
    
    def set(self, key, value):
        self._data[key] = value
    
    def delete(self, key):
        try:
            del self._data[key]
        except KeyError:
            pass

ctx = SimpleStorage()