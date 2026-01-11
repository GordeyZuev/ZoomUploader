import asyncio
import json
import os
import webbrowser
from urllib.parse import urlencode

import aiohttp


class VKTokenSetup:
    """Настройка VK токена"""

    def __init__(self, app_id: str = "54249533"):
        self.app_id = app_id

    def get_auth_url(self, scope: str = "video,groups,wall") -> str:
        """Получение URL для авторизации"""
        params = {
            "client_id": self.app_id,
            "display": "page",
            "redirect_uri": "https://oauth.vk.com/blank.html",
            "scope": scope,
            "response_type": "token",
            "v": "5.131",
        }

        return f"https://oauth.vk.com/authorize?{urlencode(params)}"

    async def get_token_interactive(self, scope: str = "video,groups,wall") -> str:
        """Получение токена"""
        print("🔑 Получение VK токена")
        print("=" * 50)

        auth_url = self.get_auth_url(scope)

        print("🌐 Открываем браузер для авторизации...")
        webbrowser.open(auth_url)

        print("\n📋 Инструкции:")
        print("1. Войдите в VK (если не авторизованы)")
        print("2. Разрешите доступ приложению")
        print("3. После авторизации вы будете перенаправлены на страницу VK")
        print("4. Скопируйте access_token из URL в адресной строке")
        print("\n⚠️  ВАЖНО: Убедитесь, что разрешили права:")
        for permission in scope.split(","):
            print(f"   ✅ {permission.strip()}")

        print("\n💡 Токен будет в URL в формате:")
        print("   access_token=YOUR_TOKEN_HERE&expires_in=86400&user_id=123456")
        print("\n⚠️  Скопируйте только значение access_token (без access_token=)")

        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            try:
                token = input(f"\nВставьте access_token (попытка {attempts + 1}/{max_attempts}): ").strip()
                if token:
                    if token.startswith("access_token="):
                        token = token.split("=")[1].split("&")[0]

                    print("🔍 Проверяем токен...")
                    is_valid, error_type = await self.test_token_with_error_type(token)

                    if is_valid:
                        print("✅ Токен действителен!")
                        # Get user_id from API
                        user_id = await self.get_user_id(token)
                        self.save_token(token, user_id)
                        return token
                    else:
                        attempts += 1
                        if error_type == "ip_mismatch":
                            print("\n🚨 ПРОБЛЕМА С IP-АДРЕСОМ:")
                            print("   Токен привязан к другому IP-адресу")
                            print("\n💡 РЕШЕНИЯ:")
                            print("   1. Получите новый токен с текущего IP-адреса")
                            print("   2. Или используйте VPN для смены IP")
                            print("   3. Или получите токен с того IP, где планируете использовать систему")
                            print("\n⚠️  ВАЖНО: Не используйте тот же токен повторно!")

                            if attempts < max_attempts:
                                print(f"\n🔄 Попробуйте еще раз ({attempts}/{max_attempts})")
                                print("   Получите НОВЫЙ токен с текущего IP-адреса")
                            else:
                                print("\n❌ Превышено максимальное количество попыток")
                                print("   Попробуйте позже или обратитесь за помощью")
                        else:
                            print("❌ Токен недействителен. Попробуйте еще раз.")

                        if attempts >= max_attempts:
                            break
                else:
                    print("❌ Токен не может быть пустым")
                    attempts += 1
            except KeyboardInterrupt:
                print("\n🛑 Отмена...")
                return None
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                attempts += 1

        return None

    async def test_token_with_error_type(self, token: str) -> tuple[bool, str]:
        """Проверка токена с возвратом типа ошибки"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"access_token": token, "v": "5.131"}
                async with session.get("https://api.vk.com/method/users.get", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            error = data["error"]
                            if error["error_code"] == 5 and error.get("error_subcode") == 1130:
                                return False, "ip_mismatch"
                            else:
                                print(f"❌ Ошибка VK API: {error['error_msg']}")
                                return False, "api_error"
                        else:
                            user = data["response"][0]
                            print(f"✅ Токен действителен! Пользователь: {user['first_name']} {user['last_name']}")
                            return True, "success"
                    else:
                        print(f"❌ HTTP ошибка: {response.status}")
                        return False, "http_error"
        except Exception as e:
            print(f"❌ Ошибка проверки: {e}")
            return False, "network_error"

    async def test_token(self, token: str) -> bool:
        """Проверка токена (обратная совместимость)"""
        is_valid, _ = await self.test_token_with_error_type(token)
        return is_valid

    async def get_user_id(self, token: str) -> int | None:
        """Получение user_id из VK API"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"access_token": token, "v": "5.131"}
                async with session.get("https://api.vk.com/method/users.get", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "response" in data and len(data["response"]) > 0:
                            return data["response"][0].get("id")
        except Exception as e:
            print(f"⚠️ Не удалось получить user_id: {e}")
        return None

    def save_token(self, token: str, user_id: int | None = None):
        """Сохранение токена с полной структурой credentials"""
        config_path = "config/vk_creds.json"
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        config = {
            "access_token": token,
            "app_id": self.app_id,
        }

        if user_id:
            config["user_id"] = user_id

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"✅ Credentials сохранены в {config_path}")
        if user_id:
            print(f"   User ID: {user_id}")

    async def check_existing_token(self) -> bool:
        """Проверка существующего токена"""
        config_path = "config/vk_creds.json"

        if not os.path.exists(config_path):
            return False

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
                token = config.get("access_token")

            if not token:
                return False

            print(f"🔍 Найден существующий токен: {token[:20]}...")
            is_valid, error_type = await self.test_token_with_error_type(token)

            if is_valid:
                print("✅ Существующий токен действителен!")
                return True
            else:
                if error_type == "ip_mismatch":
                    print("❌ Ошибка: Токен привязан к другому IP-адресу")
                    print("💡 Решение: Получите токен с того же IP, где планируете использовать систему")
                else:
                    print("❌ Существующий токен недействителен")
                return False

        except Exception as e:
            print(f"❌ Ошибка проверки существующего токена: {e}")
            return False


async def main():
    """Основная функция"""
    print("🚀 Настройка VK токена")
    print("=" * 50)

    client = VKTokenSetup()
    existing_valid = await client.check_existing_token()

    if existing_valid:
        print("\n✅ Токен уже настроен и работает!")
        print("\n📚 Примеры использования:")
        print("1. Загрузка одной записи:")
        print('   uv run python main.py --upload --vk --recordings "название_записи"')
        print("\n2. Загрузка всех готовых записей:")
        print("   uv run python main.py --upload --vk --all")
        return

    token = await client.get_token_interactive()

    if token:
        print("\n🎉 Настройка завершена успешно!")
        print("\n📚 Примеры использования:")
        print("1. Загрузка одной записи:")
        print('   uv run python main.py --upload --vk --recordings "название_записи"')
        print("\n2. Загрузка всех готовых записей:")
        print("   uv run python main.py --upload --vk --all")
    else:
        print("\n❌ Настройка не завершена")
        print("Попробуйте еще раз позже")


if __name__ == "__main__":
    asyncio.run(main())
