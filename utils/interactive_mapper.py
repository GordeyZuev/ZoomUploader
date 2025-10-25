from datetime import datetime

from logger import get_logger
from utils.formatting import normalize_datetime_string

logger = get_logger()


class InteractiveMapper:
    """Класс для интерактивного маппинга неизвестных названий."""

    def __init__(self):
        self.logger = logger

    def handle_unknown_title(
        self, original_title: str, start_time: str, default_privacy: str = "private"
    ) -> tuple[str | None, str | None, str]:
        """Интерактивная обработка неизвестного названия."""

        try:
            normalized_time = normalize_datetime_string(start_time)
            dt = datetime.fromisoformat(normalized_time)
            date_str = dt.strftime('%d.%m.%Y')
        except Exception:
            date_str = "неизвестная дата"

        from rich.console import Console
        from rich.panel import Panel

        console = Console(force_terminal=True, color_system="auto")

        console.print("\n[bold red]" + "=" * 60 + "[/bold red]")
        console.print("[bold red]❌ Правило для записи не найдено[/bold red]")
        console.print("[bold red]" + "=" * 60 + "[/bold red]")

        info_panel = Panel(
            f"[bold blue]📝 Оригинальное название:[/bold blue] {original_title}\n"
            f"[bold green]📅 Дата:[/bold green] {date_str}",
            title="[bold yellow]Информация о записи[/bold yellow]",
            border_style="yellow",
        )
        console.print(info_panel)

        youtube_title = self._get_youtube_title(original_title, date_str)
        if youtube_title is None:
            return None, None, None

        privacy_status = self._get_privacy_status(default_privacy)
        if privacy_status is None:
            return None, None, None

        description = f"Запись от {date_str}"

        console.print(
            f"\n[bold green]✅ Загружаем:[/bold green] [bold white]\"{youtube_title}\"[/bold white] [bold green]как[/bold green] [bold cyan]{privacy_status}[/bold cyan]"
        )
        console.print("[bold green]" + "=" * 60 + "[/bold green]")

        return youtube_title, description, privacy_status

    def ask_playlist_optional(self) -> str | None:
        """Опционально запросить ID плейлиста YouTube."""
        try:
            print("\n📃 Плейлист (опционально): оставьте пустым чтобы пропустить")
            playlist_id = input("   ID плейлиста (или пусто): ").strip()
            return playlist_id or None
        except KeyboardInterrupt:
            print("\n   ❌ Отменено пользователем")
            return None
        except EOFError:
            print("\n   ❌ Отменено")
            return None

    def _get_youtube_title(self, original_title: str, date_str: str) -> str | None:
        """Получение названия для YouTube от пользователя."""

        suggested_title = f"{original_title} ({date_str})"

        print("🎬 Введите название для YouTube:")
        print(f"   Предложение: {suggested_title}")
        print()

        while True:
            try:
                youtube_title = input("   Название: ").strip()

                if not youtube_title:
                    print("   ❌ Название не может быть пустым")
                    continue

                if len(youtube_title) > 100:
                    print("   ❌ Название слишком длинное (максимум 100 символов)")
                    continue

                return youtube_title

            except KeyboardInterrupt:
                print("\n   ❌ Отменено пользователем")
                return None
            except EOFError:
                print("\n   ❌ Отменено")
                return None

    def _get_privacy_status(self, default_privacy: str) -> str | None:
        """Получение статуса приватности от пользователя."""

        privacy_options = {
            "1": ("private", "приватное"),
            "2": ("unlisted", "по ссылке"),
            "3": ("public", "публичное"),
        }

        print("🔒 Статус приватности:")
        for key, (value, description) in privacy_options.items():
            marker = " (по умолчанию)" if value == default_privacy else ""
            print(f"   {key}) {value} ({description}){marker}")

        print()

        while True:
            try:
                choice = input("   Выбор [1-3]: ").strip()

                if not choice:
                    return default_privacy

                if choice in privacy_options:
                    return privacy_options[choice][0]

                print("   ❌ Неверный выбор. Введите 1, 2 или 3")

            except KeyboardInterrupt:
                print("\n   ❌ Отменено пользователем")
                return None
            except EOFError:
                print("\n   ❌ Отменено")
                return None

    def ask_continue_upload(self, remaining_count: int) -> bool:
        """Спрашивает, продолжать ли загрузку оставшихся видео."""

        if remaining_count <= 0:
            return True

        print(f"\n📊 Осталось видео для загрузки: {remaining_count}")
        print()

        while True:
            try:
                choice = input("Продолжить загрузку? [y/N]: ").strip().lower()

                if choice in ['', 'n', 'no']:
                    return False
                elif choice in ['y', 'yes']:
                    return True
                else:
                    print("   ❌ Введите 'y' для продолжения или 'n' для отмены")

            except KeyboardInterrupt:
                print("\n   ❌ Отменено пользователем")
                return False
            except EOFError:
                print("\n   ❌ Отменено")
                return False

    def show_upload_summary(
        self,
        total_count: int,
        processed_count: int,
        skipped_count: int,
        error_count: int,
        uploaded_recordings: list = None,
    ):
        """Показывает сводку по загрузке."""
        from rich.console import Console

        console = Console(force_terminal=True, color_system="auto")

        # Простой заголовок
        console.print("\n[bold cyan]📊 СВОДКА ЗАГРУЗКИ[/bold cyan]")
        console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")

        # Статистика в простом текстовом формате
        console.print(f"\n[bold blue]📁 Всего видео:[/bold blue] {total_count}")

        if processed_count > 0:
            console.print(f"[bold green]✅ Загружено успешно:[/bold green] {processed_count}")

        if skipped_count > 0:
            console.print(f"[bold yellow]⏭️ Пропущено:[/bold yellow] {skipped_count}")

        if error_count > 0:
            console.print(f"[bold red]❌ Ошибок:[/bold red] {error_count}")

        # Показываем детальную информацию о загруженных видео
        if uploaded_recordings and processed_count > 0:
            console.print("\n[bold white]📹 ЗАГРУЖЕННЫЕ ВИДЕО:[/bold white]")

            for i, recording in enumerate(uploaded_recordings, 1):
                console.print(
                    f"\n[bold cyan]{i}.[/bold cyan] [bold white]{recording.topic}[/bold white]"
                )

                # Ссылки на платформы
                has_any_link = False
                if hasattr(recording, 'youtube_url') and recording.youtube_url:
                    console.print(
                        f"    [bold red]📺 YouTube:[/bold red] [link={recording.youtube_url}]{recording.youtube_url}[/link]"
                    )
                    has_any_link = True

                if hasattr(recording, 'vk_url') and recording.vk_url:
                    console.print(
                        f"    [bold blue]📘 VK:[/bold blue] [link={recording.vk_url}]{recording.vk_url}[/link]"
                    )
                    has_any_link = True

                if not has_any_link:
                    console.print("    [dim]Ссылки недоступны[/dim]")

        # Итоговая информация
        console.print("\n[bold white]📊 ИТОГИ:[/bold white]")
        if processed_count == total_count and error_count == 0:
            console.print("[bold green]🎉 Все видео успешно загружены![/bold green]")
            console.print("[bold green]✨ Задача выполнена на 100%[/bold green]")
        elif processed_count > 0:
            success_rate = (processed_count / total_count) * 100
            console.print(f"[bold green]✅ Успешность: {success_rate:.1f}%[/bold green]")
            if error_count > 0:
                console.print("[bold yellow]⚠️ Есть ошибки, проверьте логи[/bold yellow]")
        else:
            console.print("[bold red]❌ Ни одно видео не было загружено[/bold red]")

        console.print("\n[bold cyan]🏁 ЗАВЕРШЕНО[/bold cyan]")
        console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")


# Глобальный экземпляр интерактивного маппера
_interactive_mapper = None


def get_interactive_mapper() -> InteractiveMapper:
    """Получение глобального экземпляра интерактивного маппера."""
    global _interactive_mapper
    if _interactive_mapper is None:
        _interactive_mapper = InteractiveMapper()
    return _interactive_mapper


def handle_unknown_title_interactive(
    original_title: str, start_time: str, default_privacy: str = "private"
) -> tuple[str | None, str | None, str]:
    """Удобная функция для интерактивной обработки неизвестного названия."""
    mapper = get_interactive_mapper()
    return mapper.handle_unknown_title(original_title, start_time, default_privacy)
