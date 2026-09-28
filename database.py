import os
import sqlite3
import threading

# Путь к базе. Позже на Railway можно задать DB_PATH=/data/users.db (постоянный том)
DB_PATH = os.environ.get("DB_PATH", "users.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

# Бот, фоновый поток и веб-сервер работают одновременно, поэтому все запросы идут через замок
_lock = threading.Lock()


def _run(sql, params=(), fetch=False):
    with _lock:
        cur = conn.execute(sql, params)
        result = cur.fetchall() if fetch else cur.rowcount
        conn.commit()
        return result


def init_db():
    _run('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            target_price REAL,
            direction TEXT
        )
    ''')
    # На случай старой таблицы без колонки direction
    try:
        _run('ALTER TABLE alerts ADD COLUMN direction TEXT')
    except sqlite3.OperationalError:
        pass


# direction: "above" — уведомить, когда цена >= target_price; "below" — когда <=
def add_alert(user_id, symbol, target_price, direction):
    _run(
        'INSERT INTO alerts (user_id, symbol, target_price, direction) VALUES (?, ?, ?, ?)',
        (user_id, symbol, target_price, direction),
    )


# Для фонового потока: все алерты
def get_all_alerts():
    return _run('SELECT id, user_id, symbol, target_price, direction FROM alerts', fetch=True)


# Для Mini App: алерты одного пользователя
def get_user_alerts(user_id):
    return _run(
        'SELECT id, symbol, target_price, direction FROM alerts WHERE user_id = ? ORDER BY id DESC',
        (user_id,),
        fetch=True,
    )


def delete_alert(alert_id):
    _run('DELETE FROM alerts WHERE id = ?', (alert_id,))


# Для Mini App: удаляет, только если алерт принадлежит этому пользователю
def delete_user_alert(alert_id, user_id):
    return _run('DELETE FROM alerts WHERE id = ? AND user_id = ?', (alert_id, user_id))


init_db()