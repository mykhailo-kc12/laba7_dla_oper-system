import mmap
import os
import struct
import tempfile

from src import task1_anonymous_mmap as task1


def test_set_and_get_used_size():
    """Перевіряє запис і читання used_size у mmap."""
    shared_memory = mmap.mmap(-1, task1.MMAP_SIZE)

    try:
        task1.set_used_size(shared_memory, task1.HEADER_SIZE)
        used_size = task1.get_used_size(shared_memory)

        assert used_size == task1.HEADER_SIZE

    finally:
        shared_memory.close()


def test_serialize_and_deserialize_message():
    """Перевіряє pickle-серіалізацію повідомлення."""
    message = {
        "pid": 123,
        "str": "hello",
    }

    data = task1.serialize_message(message)
    restored_message = task1.deserialize_message(data)

    assert restored_message == message


def test_make_record_contains_size_and_payload():
    """Перевіряє структуру запису: розмір і дані."""
    message = {
        "pid": 123,
        "str": "hello",
    }

    record = task1.make_record(message)
    message_size = struct.unpack("Q", record[:task1.HEADER_SIZE])[0]
    payload = record[task1.HEADER_SIZE:]

    assert message_size == len(payload)
    assert task1.deserialize_message(payload) == message


def test_read_messages_returns_written_message():
    """Перевіряє читання вручну записаного повідомлення."""
    shared_memory = mmap.mmap(-1, task1.MMAP_SIZE)

    message = {
        "pid": 123,
        "str": "hello",
    }

    try:
        record = task1.make_record(message)
        task1.set_used_size(shared_memory, task1.HEADER_SIZE)
        shared_memory.seek(task1.HEADER_SIZE)
        shared_memory.write(record)
        task1.set_used_size(
            shared_memory,
            task1.HEADER_SIZE + len(record),
        )

        messages = task1.read_messages(shared_memory)

        assert messages == [message]

    finally:
        shared_memory.close()


def test_write_message_writes_one_message():
    """Перевіряє запис одного повідомлення через flock."""
    shared_memory = mmap.mmap(-1, task1.MMAP_SIZE)

    try:
        task1.set_used_size(shared_memory, task1.HEADER_SIZE)

        with tempfile.NamedTemporaryFile() as lock_file:
            success = task1.write_message(shared_memory, lock_file)
            messages = task1.read_messages(shared_memory)

        assert success is True
        assert len(messages) == 1
        assert messages[0]["pid"] == os.getpid()
        assert isinstance(messages[0]["str"], str)

    finally:
        shared_memory.close()
