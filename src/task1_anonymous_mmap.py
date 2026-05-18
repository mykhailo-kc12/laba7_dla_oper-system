import argparse
import fcntl
import mmap
import os
import pickle
import random
import string
import struct
import sys
import tempfile
import time

# Лабораторна робота №7, завдання №1.
# Обмін даними між процесами через анонімний mmap.
# Для синхронізації доступу використовується окремий lock-файл.


HEADER_SIZE = 8
MMAP_SIZE = 65536
DEFAULT_CHILDREN = 5
MAX_TEXT_LENGTH = 40


class SharedMemoryError(Exception):
    """Помилка під час роботи зі спільною пам'яттю."""


def generate_random_text(max_length=MAX_TEXT_LENGTH):
    """
    Генерує випадковий рядок для повідомлення.

    Цей рядок буде передаватися від дочірнього процесу
    до батьківського через спільну mmap-область.
    """

    # Визначаємо випадкову довжину рядка.
    length = random.randint(10, max_length)

    # Задаємо набір символів для генерації рядка.
    symbols = string.ascii_letters + string.digits + " "

    # Формуємо рядок із випадкових символів.
    return "".join(random.choice(symbols) for _ in range(length))


def get_used_size(shared_memory):
    """
    Зчитує службове значення used_size з початку mmap.

    Це число показує, скільки байтів уже зайнято в спільній пам'яті
    і з якого місця можна записувати наступне повідомлення.
    """

    try:
        # Переходимо на початок mmap.
        shared_memory.seek(0)

        # Читаємо службові 8 байт.
        data = shared_memory.read(HEADER_SIZE)

        # Якщо даних менше 8 байт, це означає пошкодження структури.
        if len(data) != HEADER_SIZE:
            raise SharedMemoryError("Не вдалося прочитати used_size")

        # Перетворюємо байти у ціле число.
        return struct.unpack("Q", data)[0]

    except (OSError, struct.error) as error:
        raise SharedMemoryError(f"Помилка читання used_size: {error}")


def set_used_size(shared_memory, used_size):
    """
    Записує нове значення used_size у початок mmap.

    Після кожного запису повідомлення це значення оновлюється,
    щоб наступний процес знав, куди саме писати дані.
    """

    try:
        # Перевіряємо, щоб значення не виходило за межі mmap.
        if used_size < HEADER_SIZE or used_size > MMAP_SIZE:
            raise SharedMemoryError("Некоректне значення used_size")

        # Переходимо на початок mmap.
        shared_memory.seek(0)

        # Записуємо used_size як 8 байт.
        shared_memory.write(struct.pack("Q", used_size))

    except (OSError, struct.error) as error:
        raise SharedMemoryError(f"Помилка запису used_size: {error}")


def create_message():
    """
    Створює повідомлення дочірнього процесу.

    Повідомлення є словником з PID процесу та випадковим рядком,
    як і вимагається в умові лабораторної роботи.
    """

    # Повертаємо словник з PID поточного процесу і випадковим рядком.
    return {
        "pid": os.getpid(),
        "str": generate_random_text(),
    }


def serialize_message(message):
    """
    Перетворює Python-словник у бінарний формат.

    Для цього використовується pickle, щоб повідомлення можна було
    записати у mmap як послідовність байтів.
    """

    try:
        # Серіалізуємо словник у байти.
        return pickle.dumps(message)

    except pickle.PickleError as error:
        raise SharedMemoryError(f"Помилка серіалізації: {error}")


def deserialize_message(data):
    """
    Відновлює Python-словник з бінарного формату.

    Ця функція використовується батьківським процесом під час
    читання повідомлень зі спільної пам'яті.
    """

    try:
        # Перетворюємо байти назад у Python-об'єкт.
        return pickle.loads(data)

    except pickle.PickleError as error:
        raise SharedMemoryError(f"Помилка десеріалізації: {error}")


def make_record(message):
    """
    Формує бінарний запис для розміщення у mmap.

    Запис складається з двох частин: розмір повідомлення
    у перших 8 байтах і саме серіалізоване повідомлення після нього.
    """

    # Перетворюємо повідомлення у байти.
    serialized_message = serialize_message(message)

    # Визначаємо розмір серіалізованого повідомлення.
    message_size = len(serialized_message)

    # Перетворюємо розмір повідомлення у 8 байт.
    size_prefix = struct.pack("Q", message_size)

    # Повертаємо повний запис для mmap.
    return size_prefix + serialized_message


def write_message(shared_memory, lock_file):
    """
    Записує повідомлення дочірнього процесу у спільну mmap-область.

    Словник серіалізується через pickle, а перед самими даними
    записується їх розмір. flock захищає mmap, щоб кілька процесів
    не виконували запис одночасно.
    """

    # Прапорець потрібен, щоб не знімати блокування, якщо його не отримали.
    lock_acquired = False

    try:
        # Отримуємо ексклюзивне блокування перед записом.
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        lock_acquired = True

        # Створюємо словник повідомлення.
        message = create_message()

        # Формуємо повний бінарний запис.
        record = make_record(message)

        # Зчитуємо поточний кінець зайнятої області.
        used_size = get_used_size(shared_memory)

        # Рахуємо новий розмір після запису.
        new_used_size = used_size + len(record)

        # Перевіряємо, чи вистачає місця у mmap.
        if new_used_size > MMAP_SIZE:
            raise SharedMemoryError("Недостатньо місця в mmap")

        # Переходимо в кінець зайнятої області пам'яті.
        shared_memory.seek(used_size)

        # Записуємо в mmap розмір повідомлення і саме повідомлення.
        shared_memory.write(record)

        # Оновлюємо службове значення used_size.
        set_used_size(shared_memory, new_used_size)

        print(f"Процес {os.getpid()}: повідомлення записано", flush=True)

        return True

    except (OSError, struct.error, SharedMemoryError) as error:
        print(
            f"Процес {os.getpid()}: помилка запису: {error}",
            file=sys.stderr,
            flush=True,
        )

        return False

    finally:
        if lock_acquired:
            try:
                # Завжди знімаємо блокування
                # після запису або помилки.
                fcntl.flock(lock_file, fcntl.LOCK_UN)

            except OSError as error:
                message = (
                    f"Процес {os.getpid()}: "
                    f"помилка зняття блокування: "
                    f"{error}"
                )

                print(
                    message,
                    file=sys.stderr,
                    flush=True,
                )


def read_messages(shared_memory):
    """
    Зчитує всі повідомлення зі спільної mmap-області.

    Батьківський процес читає дані послідовно: спочатку розмір
    конкретного повідомлення, а потім саме серіалізоване повідомлення.
    """

    messages = []

    try:
        # Зчитуємо загальний зайнятий розмір пам'яті.
        used_size = get_used_size(shared_memory)

        # Перевіряємо службове значення.
        if used_size < HEADER_SIZE or used_size > MMAP_SIZE:
            raise SharedMemoryError("Некоректний used_size у mmap")

        # Починаємо читати після службових 8 байт.
        offset = HEADER_SIZE

        while offset < used_size:
            # Переходимо до місця, де записаний розмір повідомлення.
            shared_memory.seek(offset)

            # Читаємо 8 байт з розміром поточного повідомлення.
            size_data = shared_memory.read(HEADER_SIZE)

            # Якщо розмір прочитано не повністю, це помилка структури.
            if len(size_data) != HEADER_SIZE:
                raise SharedMemoryError("Неповний розмір повідомлення")

            # Перетворюємо 8 байт у число.
            message_size = struct.unpack("Q", size_data)[0]

            # Зсуваємо offset до початку самого повідомлення.
            offset += HEADER_SIZE

            # Перевіряємо, чи не виходить повідомлення за межі даних.
            if offset + message_size > used_size:
                raise SharedMemoryError("Повідомлення виходить за межі mmap")

            # Переходимо до серіалізованих даних повідомлення.
            shared_memory.seek(offset)

            # Читаємо повідомлення потрібного розміру.
            message_data = shared_memory.read(message_size)

            # Перевіряємо, чи повідомлення прочиталося повністю.
            if len(message_data) != message_size:
                raise SharedMemoryError("Неповне повідомлення у mmap")

            # Десеріалізуємо повідомлення.
            message = deserialize_message(message_data)

            # Додаємо повідомлення у список.
            messages.append(message)

            # Переходимо до наступного запису.
            offset += message_size

    except (OSError, struct.error, SharedMemoryError) as error:
        print(
            f"Батьківський процес: помилка читання: {error}",
            file=sys.stderr,
            flush=True,
        )

    return messages


def run_child(shared_memory, lock_file_path):
    """
    Виконує логіку дочірнього процесу.

    Дочірній процес відкриває lock-файл, трохи чекає для імітації
    паралельної роботи та записує своє повідомлення у mmap.
    """

    try:
        # Відкриваємо файл, який використовується для flock.
        with open(lock_file_path, "r+b") as lock_file:
            # Невелика затримка робить порядок запису менш передбачуваним.
            time.sleep(random.uniform(0.1, 0.5))

            # Записуємо повідомлення у спільну пам'ять.
            success = write_message(shared_memory, lock_file)

        # Якщо запис не вдався, завершуємо дочірній процес з помилкою.
        if not success:
            os._exit(1)

        # Якщо все добре, завершуємо дочірній процес успішно.
        os._exit(0)

    except OSError as error:
        print(
            f"Процес {os.getpid()}: помилка дочірнього процесу: {error}",
            file=sys.stderr,
            flush=True,
        )

        os._exit(1)


def run_parent(children_count):
    """
    Створює mmap, lock-файл і дочірні процеси.

    Після завершення всіх дочірніх процесів батьківський процес
    читає всі повідомлення зі спільної пам'яті та виводить їх.
    """

    # Наперед оголошуємо змінні для коректного очищення ресурсів.
    shared_memory = None
    lock_file_path = None

    try:
        # Створюємо анонімний mmap розміром MMAP_SIZE.
        shared_memory = mmap.mmap(-1, MMAP_SIZE)

        # Спочатку зайняті лише перші 8 байт під used_size.
        set_used_size(shared_memory, HEADER_SIZE)

        # Створюємо тимчасовий файл для організації блокування.
        with tempfile.NamedTemporaryFile(delete=False) as lock_file:
            lock_file_path = lock_file.name

        # Список PID дочірніх процесів.
        child_pids = []

        for _ in range(children_count):
            # fork створює дочірній процес.
            pid = os.fork()

            if pid == 0:
                # Цей код виконується тільки в дочірньому процесі.
                run_child(shared_memory, lock_file_path)
            else:
                # Батьківський процес зберігає PID дитини.
                child_pids.append(pid)

        for pid in child_pids:
            # Очікуємо завершення кожного дочірнього процесу.
            finished_pid, status = os.waitpid(pid, 0)

            # Перевіряємо, чи дочірній процес завершився успішно.
            if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
                print(
                    f"Процес {finished_pid} завершився з помилкою",
                    file=sys.stderr,
                    flush=True,
                )

        print("\nПовідомлення від дочірніх процесів:")

        # Після завершення дітей читаємо всі повідомлення.
        messages = read_messages(shared_memory)

        for number, message in enumerate(messages, start=1):
            print(f"{number}. PID: {message['pid']}, рядок: {message['str']}")

        return True

    except (OSError, SharedMemoryError) as error:
        print(
            f"Батьківський процес: помилка виконання: {error}",
            file=sys.stderr,
            flush=True,
        )

        return False

    finally:
        if shared_memory is not None:
            # Закриваємо mmap.
            shared_memory.close()

        if lock_file_path and os.path.exists(lock_file_path):
            # Видаляємо тимчасовий lock-файл.
            os.remove(lock_file_path)


def parse_args():
    """
    Обробляє аргументи командного рядка.

    Користувач може вказати кількість дочірніх процесів
    через параметр -n або --children.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Завдання 1: анонімний mmap "
            "та flock"
        )
    )

    parser.add_argument(
        "-n",
        "--children",
        type=int,
        default=DEFAULT_CHILDREN,
        help="Кількість дочірніх процесів",
    )

    return parser.parse_args()


def main():
    """
    Головна функція програми.

    Вона перевіряє аргументи командного рядка і запускає
    батьківський процес з потрібною кількістю дочірніх процесів.
    """

    # Отримуємо аргументи командного рядка.
    args = parse_args()

    # Кількість процесів має бути додатною.
    if args.children <= 0:
        print("Кількість процесів має бути більшою за нуль")
        return 1

    # Запускаємо основну логіку програми.
    success = run_parent(args.children)

    if not success:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
