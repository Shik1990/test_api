import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from main import app  # предполагается, что main.py лежит рядом


@pytest.fixture
def mock_app_state():
    """
    Обычная (синхронная) фикстура, которая настраивает моки
    и временно подменяет состояние приложения.
    После теста состояние очищается.
    """
    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    # Сохраняем оригинальное состояние (если было)
    original_db = getattr(app.state, "db", None)
    original_redis = getattr(app.state, "redis", None)
    app.state.db = mock_db
    app.state.redis = mock_redis
    yield mock_db, mock_redis
    # Возвращаем как было
    app.state.db = original_db
    app.state.redis = original_redis


@pytest.mark.asyncio
async def test_root_redis_miss(mock_app_state):
    """Кэш Redis пуст – код должен взять счётчик из БД и увеличить."""
    mock_db, mock_redis = mock_app_state
    mock_redis.get.return_value = None   # кэша нет
    mock_db.fetchval.return_value = 10   # в БД сейчас 10 посещений

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"visits": 11}

    mock_redis.get.assert_called_once_with("visits_count")
    mock_db.fetchval.assert_called_once_with("SELECT count(*) FROM visits")
    mock_db.execute.assert_called_once_with("INSERT INTO visits (ts) VALUES (NOW())")
    mock_redis.set.assert_called_once_with("visits_count", 11, ex=60)


@pytest.mark.asyncio
async def test_root_redis_hit(mock_app_state):
    """В кэше Redis есть значение – БД для получения счётчика не трогаем."""
    mock_db, mock_redis = mock_app_state
    mock_redis.get.return_value = "5"    # в кэше лежит 5

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"visits": 6}

    mock_redis.get.assert_called_once_with("visits_count")
    mock_db.fetchval.assert_not_called()
    mock_db.execute.assert_called_once_with("INSERT INTO visits (ts) VALUES (NOW())")
    mock_redis.set.assert_called_once_with("visits_count", 6, ex=60)
