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
            .with_directory(".", source)
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
        ).publish(f"ghcr.io/shik1990/test_api:{tag}")

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