import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from main import app  # предполагаем, что твой код лежит в api/main.py


@pytest.fixture
async def client():
    """
    Фикстура, которая мокирует базу данных и Redis,
    и возвращает асинхронного тестового клиента.
    """
    # Создаём моки
    mock_db = AsyncMock()
    mock_redis = AsyncMock()

    # Подменяем состояние приложения (без вызова startup)
    app.state.db = mock_db
    app.state.redis = mock_redis

    # ASGITransport позволяет тестировать приложение напрямую, без сервера
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # После теста можно сбросить состояние (опционально)
    app.state.db = None
    app.state.redis = None


@pytest.mark.asyncio
async def test_root_redis_miss(client):
    """Кэш Redis пуст – код должен взять счётчик из БД и увеличить."""
    # Настраиваем возвраты моков
    app.state.redis.get.return_value = None   # кэша нет
    app.state.db.fetchval.return_value = 10   # в БД сейчас 10 посещений

    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"visits": 11}   # 10 + 1

    # Проверяем, какие вызовы были сделаны
    app.state.redis.get.assert_called_once_with("visits_count")
    app.state.db.fetchval.assert_called_once_with("SELECT count(*) FROM visits")
    app.state.db.execute.assert_called_once_with(
        "INSERT INTO visits (ts) VALUES (NOW())"
    )
    app.state.redis.set.assert_called_once_with("visits_count", 11, ex=60)


@pytest.mark.asyncio
async def test_root_redis_hit(client):
    """В кэше Redis есть значение – БД для получения счётчика не трогаем."""
    app.state.redis.get.return_value = "5"    # в кэше лежит 5
    # fetchval не должен вызываться, поэтому не настраиваем его

    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"visits": 6}    # 5 + 1

    app.state.redis.get.assert_called_once_with("visits_count")
    # Убеждаемся, что запрос count(*) не уходил в БД
    app.state.db.fetchval.assert_not_called()
    app.state.db.execute.assert_called_once_with(
        "INSERT INTO visits (ts) VALUES (NOW())"
    )
    app.state.redis.set.assert_called_once_with("visits_count", 6, ex=60)
