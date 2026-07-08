import pytest


class FakeCursor:
    def __init__(self):
        self.last_sql = None
        self.last_params = None
        self.queries = []

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params
        self.queries.append(sql)

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor=None):
        self._cursor = cursor or FakeCursor()

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def test_db_config_defaults(monkeypatch):
    monkeypatch.delenv("MYSQL_HOST", raising=False)
    monkeypatch.delenv("MYSQL_PORT", raising=False)
    monkeypatch.delenv("MYSQL_USER", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_DB", raising=False)
    import importlib
    import database
    importlib.reload(database)
    assert database.DB_CONFIG["host"] == "127.0.0.1"
    assert database.DB_CONFIG["port"] == 3307
    assert database.DB_CONFIG["user"] == "root"
    assert database.DB_CONFIG["charset"] == "utf8mb4"


def test_init_tables_sql_syntax(monkeypatch):
    import database
    cursor = FakeCursor()
    monkeypatch.setattr(database, "get_conn", lambda: FakeConn(cursor=cursor))
    database.init_tables()
    assert len(cursor.queries) == 2
    assert "CREATE TABLE IF NOT EXISTS sensor_log" in cursor.queries[0]
    assert "CREATE TABLE IF NOT EXISTS command_log" in cursor.queries[1]


def test_save_chat_message_sql(monkeypatch):
    import database
    cursor = FakeCursor()
    monkeypatch.setattr(database, "get_conn", lambda: FakeConn(cursor=cursor))
    database.save_chat_message("elf2_voice", "user", "今天天气真好")
    assert "INSERT INTO chat_memory" in cursor.last_sql
    assert cursor.last_params == ("elf2_voice", "user", "今天天气真好")


def test_save_command_sql(monkeypatch):
    import database
    cursor = FakeCursor()
    monkeypatch.setattr(database, "get_conn", lambda: FakeConn(cursor=cursor))
    database.save_command("开灯", "开灯", [{"d": "led", "v": 100}], "voice")
    assert cursor.last_params[0] == "开灯"
    assert cursor.last_params[1] == "开灯"
    assert '"d": "led"' in cursor.last_params[2]
