import pickle
import random
import string
import struct


# Допоміжні функції для лабораторної роботи №7.
# Тут зібрані загальні дії: генерація рядків, pickle-серіалізація,
# робота з 8-байтовим розміром і базові перевірки значень.


SIZE_FORMAT = "=Q"
SIZE_FIELD_SIZE = 8
MIN_TEXT_LENGTH = 10
MAX_TEXT_LENGTH = 60


class UtilsError(Exception):
    """Помилка у допоміжних функціях проєкту."""


def generate_random_text(
    min_length=MIN_TEXT_LENGTH,
    max_length=MAX_TEXT_LENGTH,
):
    """
    Генерує випадковий рядок заданої довжини.

    Функція використовується для створення тексту повідомлень,
    які дочірні процеси передають батьківському процесу.
    """

    # Перевіряємо, щоб мінімальна довжина була коректною.
    if min_length < 0:
        raise UtilsError("Мінімальна довжина не може бути від'ємною")

    # Перевіряємо, щоб максимальна довжина не була меншою за мінімальну.
    if max_length < min_length:
        raise UtilsError("Максимальна довжина менша за мінімальну")

    # Визначаємо випадкову довжину рядка.
    length = random.randint(min_length, max_length)

    # Задаємо набір символів для генерації.
    symbols = string.ascii_letters + string.digits + " "

    # Формуємо рядок із випадкових символів.
    return "".join(random.choice(symbols) for _ in range(length))


def serialize_data(data):
    """
    Перетворює Python-об'єкт у бінарний формат.

    Для цього використовується pickle, щоб словники та інші об'єкти
    можна було записувати у mmap як послідовність байтів.
    """

    try:
        # Серіалізуємо об'єкт у байти.
        return pickle.dumps(data)

    except pickle.PickleError as error:
        raise UtilsError(f"Помилка серіалізації: {error}")


def deserialize_data(data):
    """
    Відновлює Python-об'єкт з бінарного формату.

    Функція використовується після читання байтів з mmap,
    щоб повернути початковий словник або інший Python-об'єкт.
    """

    try:
        # Перетворюємо байти назад у Python-об'єкт.
        return pickle.loads(data)

    except pickle.PickleError as error:
        raise UtilsError(f"Помилка десеріалізації: {error}")


def pack_size(value):
    """
    Перетворює ціле число у 8 байт.

    Так зручно зберігати розмір повідомлення перед самим
    повідомленням у спільній пам'яті.
    """

    # Перевіряємо, щоб значення було цілим числом.
    if not isinstance(value, int):
        raise UtilsError("Розмір має бути цілим числом")

    # Перевіряємо, щоб розмір не був від'ємним.
    if value < 0:
        raise UtilsError("Розмір не може бути від'ємним")

    try:
        # Пакуємо число у 8 байт.
        return struct.pack(SIZE_FORMAT, value)

    except struct.error as error:
        raise UtilsError(f"Помилка пакування розміру: {error}")


def unpack_size(data):
    """
    Перетворює 8 байт у ціле число.

    Використовується під час читання mmap, коли перед повідомленням
    потрібно дізнатися його розмір.
    """

    # Перевіряємо, що отримано рівно 8 байт.
    if len(data) != SIZE_FIELD_SIZE:
        raise UtilsError("Для розміру потрібно рівно 8 байт")

    try:
        # Розпаковуємо 8 байт у ціле число.
        return struct.unpack(SIZE_FORMAT, data)[0]

    except struct.error as error:
        raise UtilsError(f"Помилка розпакування розміру: {error}")


def validate_positive_count(value, name="value"):
    """
    Перевіряє, що число є додатним.

    Функцію можна використовувати для перевірки кількості
    дочірніх процесів або інших числових параметрів.
    """

    # Перевіряємо тип значення.
    if not isinstance(value, int):
        raise UtilsError(f"{name} має бути цілим числом")

    # Перевіряємо, що число більше нуля.
    if value <= 0:
        raise UtilsError(f"{name} має бути більшим за нуль")

    return value


def check_memory_range(offset, size, memory_size):
    """
    Перевіряє, що область пам'яті не виходить за межі mmap.

    Це корисно перед записом або читанням, коли потрібно
    перевірити offset і розмір майбутньої операції.
    """

    # Перевіряємо, щоб offset не був від'ємним.
    if offset < 0:
        raise UtilsError("Offset не може бути від'ємним")

    # Перевіряємо, щоб розмір не був від'ємним.
    if size < 0:
        raise UtilsError("Розмір області не може бути від'ємним")

    # Перевіряємо, щоб розмір mmap був додатним.
    if memory_size <= 0:
        raise UtilsError("Розмір mmap має бути більшим за нуль")

    # Перевіряємо, чи не виходить область за межі mmap.
    if offset + size > memory_size:
        raise UtilsError("Область виходить за межі mmap")

    return True


def create_message(pid, text, slot=None):
    """
    Створює словник повідомлення.

    Для першого завдання достатньо pid і str, а для другого
    можна додатково передати номер області slot.
    """

    # Формуємо базове повідомлення.
    message = {
        "pid": pid,
        "str": text,
    }

    # Для другого завдання додаємо номер області пам'яті.
    if slot is not None:
        message["slot"] = slot

    return message
