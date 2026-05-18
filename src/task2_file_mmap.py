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

# Лабораторна робота №7, завдання №2.
# Обмін повідомленнями фіксованого розміру через файловий mmap.
# Для синхронізації кожної області пам'яті використовується lockf.


STATUS_EMPTY = 0
STATUS_READY = 1
STATUS_OFFSET = 0
SIZE_OFFSET = 1
HEADER_SIZE = 9
SLOT_SIZE = 512
DEFAULT_CHILDREN = 4
MAX_TEXT_LENGTH = 60
READ_DELAY = 0.2
MAX_READ_ATTEMPTS = 50


class FileMmapError(Exception):
    """Помилка під час роботи з файловим mmap."""


def generate_random_text(max_length=MAX_TEXT_LENGTH):
    """
    Генерує випадковий рядок для повідомлення.

    Цей рядок записується дочірнім процесом у свою область
    файлового mmap і потім читається батьківським процесом.
    """

    # Визначаємо випадкову довжину рядка.
    length = random.randint(10, max_length)

    # Задаємо набір символів для генерації тексту.
    symbols = string.ascii_letters + string.digits + " "

    # Формуємо випадковий рядок.
    return "".join(random.choice(symbols) for _ in range(length))


def create_message(slot_index):
    """
    Створює повідомлення дочірнього процесу.

    У повідомленні зберігається PID процесу, номер області mmap
    і випадковий рядок, який передається батьківському процесу.
    """

    # Повертаємо словник з даними поточного процесу.
    return {
        "pid": os.getpid(),
        "slot": slot_index,
        "str": generate_random_text(),
    }


def serialize_message(message):
    """
    Перетворює Python-словник у бінарний формат.

    pickle використовується для того, щоб словник можна було
    записати у mmap як звичайну послідовність байтів.
    """

    try:
        # Серіалізуємо словник у байти.
        return pickle.dumps(message)

    except pickle.PickleError as error:
        raise FileMmapError(f"Помилка серіалізації: {error}")


def deserialize_message(data):
    """
    Відновлює Python-словник з бінарного формату.

    Батьківський процес використовує цю функцію після читання
    байтів з області mmap.
    """

    try:
        # Перетворюємо байти назад у Python-об'єкт.
        return pickle.loads(data)

    except pickle.PickleError as error:
        raise FileMmapError(f"Помилка десеріалізації: {error}")


def get_slot_offset(slot_index):
    """
    Повертає початкову позицію області mmap для конкретного процесу.

    Кожен дочірній процес пише у свою фіксовану область,
    тому offset залежить тільки від номера цієї області.
    """

    # Розмір однієї області множимо на її номер.
    return slot_index * SLOT_SIZE


def make_slot_data(message):
    """
    Формує дані фіксованого розміру для одного slot.

    На початку зберігається статус, потім розмір повідомлення,
    а після цього саме серіалізоване повідомлення.
    """

    # Перетворюємо повідомлення у байти.
    payload = serialize_message(message)

    # Перевіряємо, чи поміститься повідомлення в одну область.
    if len(payload) > SLOT_SIZE - HEADER_SIZE:
        raise FileMmapError("Повідомлення занадто велике для slot")

    # Записуємо статус готовності та розмір повідомлення.
    header = struct.pack("=BQ", STATUS_READY, len(payload))

    # Доповнюємо запис нулями до фіксованого розміру.
    padding_size = SLOT_SIZE - len(header) - len(payload)

    # Повертаємо повний запис розміром SLOT_SIZE.
    return header + payload + bytes(padding_size)


def write_slot(shared_memory, file_obj, slot_index):
    """
    Записує повідомлення у визначену область файлового mmap.

    Перед записом дочірній процес блокує тільки свою область файлу
    через lockf. Це дозволяє різним процесам працювати з різними
    областями пам'яті незалежно один від одного.
    """

    # Прапорець потрібен для коректного зняття блокування.
    lock_acquired = False

    # Обчислюємо позицію області для цього дочірнього процесу.
    offset = get_slot_offset(slot_index)

    try:
        # Блокуємо тільки свою область файлу.
        fcntl.lockf(file_obj, fcntl.LOCK_EX, SLOT_SIZE, offset)
        lock_acquired = True

        # Створюємо повідомлення для запису.
        message = create_message(slot_index)

        # Формуємо запис фіксованого розміру.
        slot_data = make_slot_data(message)

        # Переходимо до початку своєї області mmap.
        shared_memory.seek(offset)

        # Записуємо повний slot у mmap.
        shared_memory.write(slot_data)

        # Примусово синхронізуємо зміни.
        shared_memory.flush()

        print(
            f"Процес {os.getpid()}: записав повідомлення у slot {slot_index}",
            flush=True,
        )

        return True

    except (OSError, struct.error, FileMmapError) as error:
        print(
            f"Процес {os.getpid()}: помилка запису: {error}",
            file=sys.stderr,
            flush=True,
        )

        return False

    finally:
        if lock_acquired:
            try:
                # Знімаємо блокування зі своєї області.
                fcntl.lockf(file_obj, fcntl.LOCK_UN, SLOT_SIZE, offset)

            except OSError as error:
                message = (
                    f"Процес {os.getpid()}: "
                    f"помилка розблокування: "
                    f"{error}"
                )
                print(
                    message,
                    file=sys.stderr,
                    flush=True,
                )


def read_slot(shared_memory, file_obj, slot_index):
    """
    Читає одне повідомлення з визначеної області mmap.

    Батьківський процес використовує роздільне блокування lockf,
    щоб безпечно читати область, яку міг змінювати дочірній процес.
    """

    # Прапорець потрібен для коректного зняття блокування.
    lock_acquired = False

    # Обчислюємо позицію потрібної області mmap.
    offset = get_slot_offset(slot_index)

    try:
        # Отримуємо роздільне блокування для читання.
        fcntl.lockf(file_obj, fcntl.LOCK_SH, SLOT_SIZE, offset)
        lock_acquired = True

        # Переходимо до початку потрібного slot.
        shared_memory.seek(offset)

        # Читаємо службовий статус області.
        status_data = shared_memory.read(1)

        # Якщо статус не прочитався, структура пошкоджена.
        if len(status_data) != 1:
            raise FileMmapError("Не вдалося прочитати статус slot")

        # Перетворюємо статус з байтів у число.
        status = status_data[0]

        # Якщо повідомлення ще немає, повертаємо None.
        if status != STATUS_READY:
            return None

        # Читаємо 8 байт з розміром повідомлення.
        size_data = shared_memory.read(8)

        # Перевіряємо, чи розмір прочитано повністю.
        if len(size_data) != 8:
            raise FileMmapError("Не вдалося прочитати розмір slot")

        # Перетворюємо розмір повідомлення у число.
        message_size = struct.unpack("=Q", size_data)[0]

        # Перевіряємо, чи розмір не виходить за межі slot.
        if message_size > SLOT_SIZE - HEADER_SIZE:
            raise FileMmapError("Некоректний розмір повідомлення")

        # Читаємо серіалізоване повідомлення.
        message_data = shared_memory.read(message_size)

        # Перевіряємо повноту прочитаного повідомлення.
        if len(message_data) != message_size:
            raise FileMmapError("Неповне повідомлення у slot")

        # Повертаємо відновлений словник.
        return deserialize_message(message_data)

    except (OSError, struct.error, FileMmapError) as error:
        print(
            f"Батьківський процес: помилка читання: {error}",
            file=sys.stderr,
            flush=True,
        )

        return None

    finally:
        if lock_acquired:
            try:
                # Знімаємо роздільне блокування після читання.
                fcntl.lockf(file_obj, fcntl.LOCK_UN, SLOT_SIZE, offset)

            except OSError as error:
                message = (
                    f"Батьківський процес: "
                    f"помилка розблокування: "
                    f"{error}"
                )

                print(
                    message,
                    file=sys.stderr,
                    flush=True,
                )


def read_all_slots(shared_memory, file_obj, slots_count, received):
    """
    Періодично читає всі області mmap.

    Якщо у певному slot вже є повідомлення, воно додається
    до словника received і більше повторно не виводиться.
    """

    for slot_index in range(slots_count):
        # Пропускаємо вже прочитані області.
        if slot_index in received:
            continue

        # Пробуємо прочитати повідомлення з поточного slot.
        message = read_slot(shared_memory, file_obj, slot_index)

        # Якщо повідомлення ще немає, переходимо далі.
        if message is None:
            continue

        # Зберігаємо отримане повідомлення.
        received[slot_index] = message

        print(
            f"Отримано slot {slot_index}: "
            f"PID {message['pid']}, рядок: {message['str']}",
            flush=True,
        )


def run_child(file_path, slots_count, slot_index):
    """
    Виконує логіку дочірнього процесу.

    Процес відкриває файл, підключає його до mmap і записує
    повідомлення у свою заздалегідь визначену область.
    """

    try:
        # Відкриваємо файл для читання і запису.
        with open(file_path, "r+b") as file_obj:
            # Відображаємо весь файл у пам'ять.
            memory_size = slots_count * SLOT_SIZE
            shared_memory = mmap.mmap(file_obj.fileno(), memory_size)

            try:
                # Затримка імітує паралельну роботу процесів.
                time.sleep(random.uniform(0.1, 0.7))

                # Записуємо повідомлення у свій slot.
                success = write_slot(shared_memory, file_obj, slot_index)

            finally:
                # Закриваємо mmap у дочірньому процесі.
                shared_memory.close()

        # Якщо запис не вдався, завершуємо процес з помилкою.
        if not success:
            os._exit(1)

        # Якщо все добре, завершуємо процес успішно.
        os._exit(0)

    except OSError as error:
        print(
            f"Процес {os.getpid()}: помилка дочірнього процесу: {error}",
            file=sys.stderr,
            flush=True,
        )

        os._exit(1)


def create_mmap_file(file_path, file_size):
    """
    Створює файл потрібного розміру для файлового mmap.

    Файл заповнюється нулями через truncate, після чого його
    можна безпечно відобразити у пам'ять.
    """

    try:
        # Створюємо або очищуємо файл.
        with open(file_path, "w+b") as file_obj:
            # Задаємо фіксований розмір файлу.
            file_obj.truncate(file_size)

    except OSError as error:
        raise FileMmapError(f"Не вдалося створити файл mmap: {error}")


def wait_children(child_pids):
    """
    Очікує завершення всіх дочірніх процесів.

    Якщо якийсь дочірній процес завершується з помилкою,
    батьківський процес виводить повідомлення у stderr.
    """

    for pid in child_pids:
        try:
            # Очікуємо завершення конкретного дочірнього процесу.
            finished_pid, status = os.waitpid(pid, 0)

            # Перевіряємо код завершення процесу.
            if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
                print(
                    f"Процес {finished_pid} завершився з помилкою",
                    file=sys.stderr,
                    flush=True,
                )

        except OSError as error:
            print(
                f"Помилка очікування процесу {pid}: {error}",
                file=sys.stderr,
                flush=True,
            )


def run_parent(children_count):
    """
    Створює файл, mmap і дочірні процеси.

    Батьківський процес періодично читає всі області пам'яті
    з роздільним блокуванням і виводить отримані повідомлення.
    """

    # Наперед оголошуємо змінні для очищення ресурсів.
    file_path = None
    shared_memory = None

    try:
        # Розмір файлу залежить від кількості областей.
        file_size = children_count * SLOT_SIZE

        # Створюємо тимчасовий файл для mmap.
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file_path = tmp_file.name

        # Готуємо файл потрібного розміру.
        create_mmap_file(file_path, file_size)

        # Відкриваємо файл для mmap у батьківському процесі.
        with open(file_path, "r+b") as file_obj:
            # Відображаємо файл у пам'ять.
            shared_memory = mmap.mmap(file_obj.fileno(), file_size)

            # Тут зберігаються вже отримані повідомлення.
            received = {}

            # Список PID дочірніх процесів.
            child_pids = []

            for slot_index in range(children_count):
                # Створюємо дочірній процес.
                pid = os.fork()

                if pid == 0:
                    # Дочірній процес пише у свій slot.
                    run_child(file_path, children_count, slot_index)
                else:
                    # Батько зберігає PID дочірнього процесу.
                    child_pids.append(pid)

            print("Очікування повідомлень від дочірніх процесів...\n")

            for _ in range(MAX_READ_ATTEMPTS):
                # Читаємо всі області mmap.
                read_all_slots(
                    shared_memory,
                    file_obj,
                    children_count,
                    received,
                )

                # Якщо всі повідомлення отримано, завершуємо читання.
                if len(received) == children_count:
                    break

                # Пауза між періодичними читаннями.
                time.sleep(READ_DELAY)

            # Очікуємо завершення всіх дочірніх процесів.
            wait_children(child_pids)

            # Робимо фінальне читання після завершення процесів.
            read_all_slots(
                shared_memory,
                file_obj,
                children_count,
                received,
            )

            print(f"\nУсього отримано повідомлень: {len(received)}")

            return len(received) == children_count

    except (OSError, FileMmapError) as error:
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

        if file_path and os.path.exists(file_path):
            # Видаляємо тимчасовий файл mmap.
            os.remove(file_path)


def parse_args():
    """
    Обробляє аргументи командного рядка.

    Користувач може вказати кількість дочірніх процесів
    через параметр -n або --children.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Завдання 2: файловий mmap "
            "та lockf"
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
