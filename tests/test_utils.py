import pytest

from src import utils


def test_generate_random_text_length():
    """Перевіряє, що випадковий рядок має правильну довжину."""
    text = utils.generate_random_text(5, 10)

    assert 5 <= len(text) <= 10


def test_generate_random_text_invalid_range():
    """Перевіряє помилку для некоректного діапазону довжини."""
    with pytest.raises(utils.UtilsError):
        utils.generate_random_text(10, 5)


def test_serialize_and_deserialize_data():
    """Перевіряє серіалізацію та десеріалізацію словника."""
    data = {
        "pid": 123,
        "str": "test message",
    }

    binary_data = utils.serialize_data(data)
    restored_data = utils.deserialize_data(binary_data)

    assert restored_data == data


def test_pack_and_unpack_size():
    """Перевіряє пакування та розпакування розміру."""
    packed_size = utils.pack_size(128)
    unpacked_size = utils.unpack_size(packed_size)

    assert unpacked_size == 128


def test_unpack_size_invalid_length():
    """Перевіряє помилку, якщо розмір має не 8 байт."""
    with pytest.raises(utils.UtilsError):
        utils.unpack_size(b"123")


def test_validate_positive_count():
    """Перевіряє, що додатне число проходить валідацію."""
    result = utils.validate_positive_count(3, "count")

    assert result == 3


def test_validate_positive_count_error():
    """Перевіряє помилку для недодатного числа."""
    with pytest.raises(utils.UtilsError):
        utils.validate_positive_count(0, "count")


def test_check_memory_range():
    """Перевіряє коректну область у межах mmap."""
    result = utils.check_memory_range(10, 20, 100)

    assert result is True


def test_check_memory_range_error():
    """Перевіряє помилку, якщо область виходить за межі mmap."""
    with pytest.raises(utils.UtilsError):
        utils.check_memory_range(90, 20, 100)


def test_create_message_without_slot():
    """Перевіряє створення повідомлення без номера slot."""
    message = utils.create_message(123, "hello")

    assert message == {
        "pid": 123,
        "str": "hello",
    }


def test_create_message_with_slot():
    """Перевіряє створення повідомлення з номером slot."""
    message = utils.create_message(123, "hello", slot=2)

    assert message == {
        "pid": 123,
        "str": "hello",
        "slot": 2,
    }
