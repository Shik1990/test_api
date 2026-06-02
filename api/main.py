from fastapi import FastAPI
import os
import asyncpg
import redis.asyncio as redis
import asyncio
from contextlib import asynccontextmanager

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://myuser:mypass@db:5432/mydb")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


async def connect_to_db():
    for attempt in range(10):
        try:
            conn = await asyncpg.connect(DATABASE_URL, timeout=5)
            return conn
        except Exception as e:
            print(f"DB connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    raise RuntimeError("Could not connect to DB")



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.db = await connect_to_db()
    await app.state.db.execute(
        "CREATE TABLE IF NOT EXISTS visits (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW())")
    app.state.redis = await redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

    yield  # Точка перехода между startup и shutdown

    # Shutdown
    await app.state.redis.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    # Пробуем взять счётчик из кэша Redis
    cached = await app.state.redis.get("visits_count")
    if cached is not None:
        count = int(cached)
    else:
        count = await app.state.db.fetchval("SELECT count(*) FROM visits")
    # Увеличиваем счётчик в БД и кэше
    await app.state.db.execute("INSERT INTO visits (ts) VALUES (NOW())")
    new_count = count + 1
    await app.state.redis.set("visits_count", new_count, ex=60)  # кэш на 60 секунд
    return {"visits": new_count}