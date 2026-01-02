import json
import os
import webbrowser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class YouTubeTokenSetup:
    """Интерактивная настройка OAuth для YouTube и сохранение токена в bundle."""

    def __init__(self, bundle_path: str = "config/youtube_creds.json", default_scopes: list[str] | None = None):
        self.bundle_path = bundle_path
        self.default_scopes = default_scopes or [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ]

    def _load_bundle(self) -> dict:
        if not os.path.exists(self.bundle_path):
            return {}
        try:
            with open(self.bundle_path, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_bundle(self, bundle: dict) -> None:
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        with open(self.bundle_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)
        print(f"✅ Данные сохранены в {self.bundle_path}")

    def _ensure_client_secrets(self, bundle: dict) -> dict:
        # Если client_secrets уже есть — выходим
        if isinstance(bundle.get("client_secrets"), dict):
            return bundle

        print("\n🔧 Требуются client_secrets для Google OAuth")
        print("Вы можете:")
        print("  1) Вставить полный JSON client_secret (из Google Cloud)")
        print("  2) Или ввести client_id и client_secret вручную")

        raw = input("\nВставьте JSON client_secrets или оставьте пустым для ручного ввода: ").strip()
        if raw:
            try:
                data = json.loads(raw)
                if "installed" in data:
                    client_secrets = {"installed": data["installed"]}
                elif "web" in data:
                    client_secrets = {"installed": data["web"]}
                else:
                    client_secrets = data
                bundle["client_secrets"] = client_secrets
                self._save_bundle(bundle)
                return bundle
            except Exception as e:
                print(f"❌ Не удалось разобрать JSON: {e}")

        client_id = input("client_id: ").strip()
        client_secret = input("client_secret: ").strip()
        bundle["client_secrets"] = {
            "installed": {
                "client_id": client_id,
                "project_id": "youtube-upload",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": client_secret,
                "redirect_uris": ["http://localhost"],
            }
        }
        self._save_bundle(bundle)
        return bundle

    def _build_credentials_from_bundle(self, bundle: dict, scopes: list[str]) -> Credentials | None:
        # Пробуем восстановить из сохранённого токена
        token_obj = bundle.get("token")
        if isinstance(token_obj, dict):
            try:
                # Восстановление через словарь параметров
                creds = Credentials(
                    token=token_obj.get("token"),
                    refresh_token=token_obj.get("refresh_token"),
                    token_uri=token_obj.get("token_uri"),
                    client_id=token_obj.get("client_id"),
                    client_secret=token_obj.get("client_secret"),
                    scopes=token_obj.get("scopes") or scopes,
                )
                return creds
            except Exception:
                pass

        # Пробуем восстановить из строки JSON токена, если сохранено как строка
        if isinstance(token_obj, str):
            try:
                creds = Credentials.from_authorized_user_info(json.loads(token_obj), scopes)
                return creds
            except Exception:
                pass

        # Пробуем прочитать файл как plain credentials.json
        try:
            return Credentials.from_authorized_user_file(self.bundle_path, scopes)
        except Exception:
            return None

    def _get_flow(self, bundle: dict, scopes: list[str]) -> InstalledAppFlow:
        client_secrets_data = bundle.get("client_secrets")
        if isinstance(client_secrets_data, dict):
            return InstalledAppFlow.from_client_config(client_secrets_data, scopes)

        # Если bundle не содержит client_secrets: ищем альтернативы
        if os.path.exists(self.bundle_path):
            return InstalledAppFlow.from_client_secrets_file(self.bundle_path, scopes)

        env_path = os.getenv("YT_CLIENT_SECRETS")
        if env_path and os.path.exists(env_path):
            return InstalledAppFlow.from_client_secrets_file(env_path, scopes)

        default_secrets = os.path.join("config", "youtube_client_secrets.json")
        if os.path.exists(default_secrets):
            return InstalledAppFlow.from_client_secrets_file(default_secrets, scopes)

        raise FileNotFoundError(
            "Не найден файл client_secrets. Укажите путь в YT_CLIENT_SECRETS или создайте config/youtube_client_secrets.json"
        )

    def _open_browser_hint(self) -> None:
        print("🌐 Откроется окно браузера для авторизации Google (если не открылось — откройте ссылку вручную).")

    def _ensure_token_fresh(self, creds: Credentials, scopes: list[str]) -> Credentials | None:
        try:
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    return None
            return creds
        except Exception:
            return None

    def setup(self) -> bool:
        print("🚀 Настройка YouTube OAuth")
        print("=" * 50)

        bundle = self._load_bundle()
        scopes = bundle.get("scopes") or (bundle.get("token", {}) or {}).get("scopes") or self.default_scopes

        # Если доступный токен уже рабочий — как в setup_vk, просто выходим
        existing = self._build_credentials_from_bundle(bundle, scopes)
        existing = self._ensure_token_fresh(existing, scopes) if existing else None
        if existing:
            try:
                service = build("youtube", "v3", credentials=existing)
                service.channels().list(part="id", mine=True).execute()
                print("✅ Существующий токен действителен!")
                # Обновим сохранение после refresh
                try:
                    token_json = json.loads(existing.to_json())
                    if isinstance(bundle.get("client_secrets"), dict):
                        bundle["token"] = token_json
                        bundle["scopes"] = scopes
                        self._save_bundle(bundle)
                except Exception:
                    pass
                print("\n📚 Примеры использования:")
                print("1. Загрузка одной записи:")
                print('   uv run python main.py --upload --youtube --recordings "название_записи"')
                print("\n2. Загрузка всех готовых записей:")
                print("   uv run python main.py --upload --youtube --all")
                return True
            except Exception:
                pass

        # Гарантируем наличие client_secrets в bundle через интерактивный ввод
        bundle = self._ensure_client_secrets(bundle)

        print("🔑 Требуется авторизация Google")
        flow = self._get_flow(bundle, scopes)
        self._open_browser_hint()
        creds = flow.run_local_server(port=0)

        if not creds:
            print("❌ Не удалось получить учетные данные")
            return False

        # Быстрая проверка: пробуем выполнить простой вызов API
        try:
            service = build("youtube", "v3", credentials=creds)
            service.channels().list(part="id", mine=True).execute()
            print("✅ Проверка API прошла успешно")
        except HttpError as e:
            # Если, несмотря на creds, получаем проблемы доступа — переавторизуемся
            print(f"⚠️ Ошибка доступа к API: {e}. Будет выполнена повторная авторизация...")
            flow = self._get_flow(bundle, scopes)
            self._open_browser_hint()
            creds = flow.run_local_server(port=0)
        except Exception:
            # Нефатально, продолжаем сохранение токена
            pass

        # Сохраняем обратно в bundle: обновляем/добавляем token
        try:
            token_json = json.loads(creds.to_json())
        except Exception:
            print("❌ Не удалось сериализовать токен")
            return False

        # Если в bundle есть client_secrets — сохраняем token рядом; иначе пишем как plain credentials
        if isinstance(bundle.get("client_secrets"), dict):
            bundle["token"] = token_json
            bundle["scopes"] = scopes
            self._save_bundle(bundle)
        else:
            # Пишем как обычный credentials файл
            with open(self.bundle_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            print(f"✅ Токен сохранен в {self.bundle_path}")

        print("\n🎉 Настройка YouTube завершена успешно!")
        print("\n📚 Примеры использования:")
        print("1. Загрузка одной записи:")
        print('   uv run python main.py --upload --youtube --recordings "название_записи"')
        print("\n2. Загрузка всех готовых записей:")
        print("   uv run python main.py --upload --youtube --all")
        return True


if __name__ == "__main__":
    # Пытаемся открыть страницу согласия в системном браузере при необходимости
    try:
        webbrowser.get()
    except Exception:
        pass

    setup = YouTubeTokenSetup()
    success = setup.setup()
    if not success:
        raise SystemExit(1)
    raise SystemExit(0)
