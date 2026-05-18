import mmap
import os
import struct

import pytest

from src import task2_file_mmap as task2


def test_get_slot_offset():
    """Перевіряє обчислення початку області slot."""
    assert task2.get_slot_offset(0) == 0
    assert task2.get_slot_offset(3) == 3 * task2.SLOT_SIZE


def test_make_slot_data_fixed_size():
    """Перевіряє, що запис slot має фіксований розмір."""
    message = {
        "pid": 123,
        "slot": 1,
        "str": "hello",
    }

    slot_data = task2.make_slot_data(message)

    assert len(slot_data) == task2.SLOT_SIZE
    assert slot_data[task2.STATUS_OFFSET] == task2.STATUS_READY


def test_make_slot_data_contains_payload_size():
    """Перевіряє службове поле з розміром повідомлення."""
    message = {
        "pid": 123,
        "slot": 1,
        "str": "hello",
    }

    slot_data = task2.make_slot_data(message)
    size_start = task2.SIZE_OFFSET
    size_end = task2.SIZE_OFFSET + 8
    message_size = struct.unpack("=Q", slot_data[size_start:size_end])[0]

    assert message_size > 0
    assert message_size <= task2.SLOT_SIZE - task2.HEADER_SIZE


def test_make_slot_data_too_large():
    """Перевіряє помилку, якщо повідомлення не поміщається у slot."""
    message = {
        "pid": 123,
        "slot": 1,
        "str": "x" * task2.SLOT_SIZE,
    }

    with pytest.raises(task2.FileMmapError):
        task2.make_slot_data(message)


def test_create_mmap_file_size(tmp_path):
    """Перевіряє створення файлу потрібного розміру."""
    file_path = tmp_path / "memory.dat"
    file_size = task2.SLOT_SIZE * 2

    task2.create_mmap_file(file_path, file_size)

    assert file_path.stat().st_size == file_size


def test_read_empty_slot_returns_none(tmp_path):
    """Перевіряє, що порожній slot повертає None."""
    file_path = tmp_path / "memory.dat"
    file_size = task2.SLOT_SIZE

    task2.create_mmap_file(file_path, file_size)

    with open(file_path, "r+b") as file_obj:
        shared_memory = mmap.mmap(file_obj.fileno(), file_size)

        try:
            result = task2.read_slot(shared_memory, file_obj, 0)

            assert result is None

        finally:
            shared_memory.close()


def test_write_and_read_slot(tmp_path):
    """Перевіряє запис і читання повідомлення через lockf."""
    file_path = tmp_path / "memory.dat"
    file_size = task2.SLOT_SIZE * 2

    task2.create_mmap_file(file_path, file_size)

    with open(file_path, "r+b") as file_obj:
        shared_memory = mmap.mmap(file_obj.fileno(), file_size)

        try:
            success = task2.write_slot(shared_memory, file_obj, 1)
            message = task2.read_slot(shared_memory, file_obj, 1)

            assert success is True
            assert message["pid"] == os.getpid()
            assert message["slot"] == 1
            assert isinstance(message["str"], str)

        finally:
            shared_memory.close()
