"""Хранилище состояний - один словарь на весь процесс"""

_data = {}

class StorageProxy:
    """Прокси для обратной совместимости с ctx.get/set/delete"""
    def get(self, key, default=None):
        return _data.get(key, default)
    
    def set(self, key, value):
        _data[key] = value
    
    def delete(self, key):
        _data.pop(key, None)

# Единый экземпляр для всего процесса
ctx = StorageProxy()
