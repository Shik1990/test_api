# pipeline.py
import dagger
from dagger import dag, function, object_type


@object_type
class CI:
    """Пайплайн для FastAPI-проекта"""

    @function
    async def build(self, source: dagger.Directory) -> dagger.Container:
        """Сборка Docker-образа с кэшированием"""
        return (
            dag.container()
            .from_("python:3.11-slim")
            # Кэшируем пакеты через volume
            .with_mounted_cache(
                "/root/.cache/pip",
                dag.cache_volume("pip-cache")
            )
            .with_workdir("/app")
            # Установка зависимостей
            .with_exec(["pip", "install", "-r", "requirements.txt"])
            .with_exec(["pip", "install", "pytest"])
            # Копируем код
            .with_directory(".", source)
        )

    @function
    async def test(self, container: dagger.Container) -> str:
        """Запуск тестов"""
        return await container.with_exec(["pytest", "-v"]).stdout()

    @function
    async def push(self, container: dagger.Container, tag: str) -> str:
        """Публикация образа в GitHub Container Registry"""
        return await container.with_registry_auth(
            "ghcr.io",
            "github.com",
            dagger.secret_from_env("GITHUB_TOKEN")
        ).publish(f"ghcr.io/shik1990/test_api:дд")

    @function
    async def test_with_services(self, source: dagger.Directory) -> str:
        # Запускаем PostgreSQL
        db = (
            dag.container()
            .from_("postgres:16-alpine")
            .with_env_variable("POSTGRES_USER", "myuser")
            .with_env_variable("POSTGRES_PASSWORD", "mypass")
            .with_env_variable("POSTGRES_DB", "mydb")
            .with_exposed_port(5432)
        )

        # Запускаем Redis
        redis = (
            dag.container()
            .from_("redis:7-alpine")
            .with_exposed_port(6379)
        )

        # Собираем приложение
        app = await self.build(source)

        # Запускаем тесты с подключенными сервисами
        return await app.with_service_binding("db", db).with_service_binding("redis", redis).with_exec(
            ["pytest", "-v"]).stdout()

    @function
    async def run(self, source: dagger.Directory, tag: str = "latest") -> str:
        """Запуск пайплайна end-to-end"""
        # Сборка образа
        build_container = await self.build(source)

        # Тестирование
        test_result = await self.test(build_container)
        print(f"Tests result:\n{test_result}")

        # Публикация (только в main)
        if tag == "main":
            push_result = await self.push(build_container, tag)
            return f"Tests passed. Image pushed: {push_result}"

        return "Tests passed. No push (not main branch)"

    @function
    async def debug(self, source: dagger.Directory) -> str:
        """Отладка: показывает содержимое директории"""
        return await (
            dag.container()
            .from_("alpine")
            .with_directory("/", source)
            .with_exec(["ls", "-la", "/"])
            .stdout()
        )