from threading import Lock

_user_locks = {}
_global_lock = Lock()
_stop_flags = {}


def acquire_user_lock(user_id: int) -> bool:
    with _global_lock:
        if user_id not in _user_locks:
            _user_locks[user_id] = Lock()
        lock = _user_locks[user_id]
    return lock.acquire(blocking=False)


def release_user_lock(user_id: int):
    with _global_lock:
        lock = _user_locks.get(user_id)
    if lock and lock.locked():
        lock.release()


def request_stop(user_id: int):
    _stop_flags[user_id] = True


def consume_stop(user_id: int) -> bool:
    return _stop_flags.pop(user_id, False)
