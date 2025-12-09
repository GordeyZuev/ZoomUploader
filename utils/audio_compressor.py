"""Сжатие и обработка аудио файлов"""

import asyncio
import os
from pathlib import Path

from logger import get_logger

logger = get_logger()


class AudioCompressor:
    """Компрессор аудио для сжатия и разбиения файлов"""

    def __init__(
        self,
        target_bitrate: str = "64k",
        target_sample_rate: int = 16000,
        max_file_size_mb: int = 25,
    ):
        self.target_bitrate = target_bitrate
        self.target_sample_rate = target_sample_rate
        self.max_file_size_mb = max_file_size_mb
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    async def compress_audio(
        self, input_path: str, output_path: str | None = None
    ) -> str:
        """
        Сжатие аудио файла.

        Args:
            input_path: Путь к исходному аудио файлу
            output_path: Путь для сохранения сжатого файла (если None, создается автоматически)

        Returns:
            Путь к сжатому файлу
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Аудио файл не найден: {input_path}")

        # Проверяем размер исходного файла
        file_size = os.path.getsize(input_path)
        file_size_mb = file_size / (1024 * 1024)

        logger.info(f"📊 Исходный файл: {file_size_mb:.2f} МБ")

        # Если файл уже меньше лимита, можно вернуть исходный путь
        # Но лучше все равно сжать до оптимальных параметров
        if file_size <= self.max_file_size_bytes and file_size_mb < 10:
            logger.info("✅ Файл уже достаточно мал, но сжимаем для оптимизации")

        # Определяем путь для выходного файла
        if output_path is None:
            input_path_obj = Path(input_path)
            output_path = str(
                input_path_obj.parent / f"{input_path_obj.stem}_compressed.mp3"
            )

        # Создаем директорию, если нужно
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Команда FFmpeg для сжатия
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vn',  # Без видео
            '-acodec', 'libmp3lame',  # MP3 кодек
            '-ab', self.target_bitrate,  # Битрейт
            '-ar', str(self.target_sample_rate),  # Частота дискретизации
            '-ac', '1',  # Моно (для речи достаточно)
            '-y',  # Перезаписать файл, если существует
            output_path,
        ]

        try:
            logger.info(f"🔧 Сжатие аудио: {input_path}")
            logger.info(
                f"🔧 Параметры: битрейт={self.target_bitrate}, "
                f"частота={self.target_sample_rate}Hz, моно"
            )

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Неизвестная ошибка"
                raise RuntimeError(f"Ошибка сжатия аудио: {error_msg}")

            if not os.path.exists(output_path):
                raise RuntimeError(f"Сжатый файл не был создан: {output_path}")

            # Проверяем размер сжатого файла
            compressed_size = os.path.getsize(output_path)
            compressed_size_mb = compressed_size / (1024 * 1024)

            logger.info(f"✅ Аудио сжато: {compressed_size_mb:.2f} МБ")

            if compressed_size > self.max_file_size_bytes:
                logger.warning(
                    f"⚠️ Сжатый файл все еще превышает лимит: "
                    f"{compressed_size_mb:.2f} МБ > {self.max_file_size_mb} МБ"
                )
                # Можно попробовать еще больше сжать, но для начала оставим так

            return output_path

        except Exception as e:
            logger.error(f"❌ Ошибка сжатия аудио: {e}")
            raise

    async def get_audio_info(self, audio_path: str) -> dict:
        """Получение информации об аудио файле"""
        import json

        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            audio_path,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"Ошибка получения информации об аудио: {stderr.decode()}")

            info = json.loads(stdout.decode())
            audio_stream = next(
                (s for s in info['streams'] if s['codec_type'] == 'audio'), None
            )

            if not audio_stream:
                raise RuntimeError("Аудио поток не найден")

            return {
                'duration': float(info['format']['duration']),
                'size': int(info['format']['size']),
                'bitrate': int(info['format'].get('bit_rate', 0)),
                'sample_rate': int(audio_stream.get('sample_rate', 0)),
                'channels': int(audio_stream.get('channels', 0)),
                'codec': audio_stream.get('codec_name', 'unknown'),
            }

        except Exception as e:
            logger.error(f"❌ Ошибка получения информации об аудио: {e}")
            raise

    async def split_audio(
        self, audio_path: str, max_size_mb: float = 20.0, output_dir: str | None = None
    ) -> list[str]:
        """
        Разбиение аудио файла на части, если он слишком большой.

        Args:
            audio_path: Путь к аудио файлу
            max_size_mb: Максимальный размер одной части в МБ
            output_dir: Директория для сохранения частей (если None, используется та же директория)

        Returns:
            Список путей к частям файла
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        # Получаем информацию об аудио
        audio_info = await self.get_audio_info(audio_path)
        duration = audio_info['duration']
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

        logger.info(f"📊 Разбиение аудио: {file_size_mb:.2f} МБ, длительность: {duration:.1f}с")

        # Если файл уже достаточно мал, возвращаем его как есть
        if file_size_mb <= max_size_mb:
            logger.info("✅ Файл не требует разбиения")
            return [audio_path]

        # Вычисляем количество частей
        # Оцениваем размер одной секунды аудио
        size_per_second = file_size_mb / duration
        # Вычисляем длительность одной части
        # (без дополнительного запаса, т.к. max_size_mb уже с запасом)
        duration_per_part = max_size_mb / size_per_second

        # Вычисляем минимальное количество частей
        num_parts = int(duration / duration_per_part)
        if num_parts * duration_per_part < duration:
            num_parts += 1

        actual_duration_per_part = duration / num_parts
        estimated_size_per_part = actual_duration_per_part * size_per_second

        logger.info(
            f"🔪 Разбиение на {num_parts} частей, "
            f"~{actual_duration_per_part:.1f}с каждая (~{estimated_size_per_part:.1f} МБ каждая)"
        )

        # Определяем директорию для частей
        if output_dir is None:
            output_dir = os.path.dirname(audio_path)
        else:
            os.makedirs(output_dir, exist_ok=True)

        input_path_obj = Path(audio_path)

        # Асинхронная функция для создания одной части
        async def create_part(i: int) -> str:
            """Создание одной части аудио"""
            start_time = i * actual_duration_per_part
            part_duration = actual_duration_per_part

            # Для последней части берем оставшееся время
            if i == num_parts - 1:
                part_duration = duration - start_time

            part_filename = f"{input_path_obj.stem}_part_{i+1:03d}.mp3"
            part_path = os.path.join(output_dir, part_filename)

            cmd = [
                'ffmpeg',
                '-i', audio_path,
                '-ss', str(start_time),
                '-t', str(part_duration),
                '-vn',
                '-acodec', 'libmp3lame',
                '-ab', self.target_bitrate,
                '-ar', str(self.target_sample_rate),
                '-ac', '1',
                '-y',
                part_path,
            ]

            try:
                end_time = start_time + part_duration
                logger.info(
                    f"🔪 Создание части {i+1}/{num_parts}: "
                    f"{start_time:.1f}s - {end_time:.1f}s"
                )

                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Неизвестная ошибка"
                    raise RuntimeError(f"Ошибка создания части {i+1}: {error_msg}")

                if not os.path.exists(part_path):
                    raise RuntimeError(f"Часть {i+1} не была создана: {part_path}")

                part_size_mb = os.path.getsize(part_path) / (1024 * 1024)

                # Проверяем, что часть не превышает лимит
                if part_size_mb > self.max_file_size_mb:
                    error_msg = (
                        f"Часть {i+1}/{num_parts} превышает лимит: "
                        f"{part_size_mb:.2f} МБ > {self.max_file_size_mb} МБ. "
                        f"Попробуйте уменьшить max_size_mb в конфигурации."
                    )
                    logger.error(f"❌ {error_msg}")
                    raise ValueError(error_msg)
                elif part_size_mb > self.max_file_size_mb * 0.95:
                    logger.warning(
                        f"⚠️ Часть {i+1}/{num_parts} близка к лимиту: "
                        f"{part_size_mb:.2f} МБ (лимит: {self.max_file_size_mb} МБ)"
                    )

                logger.info(f"✅ Часть {i+1}/{num_parts} создана: {part_size_mb:.2f} МБ")
                return part_path

            except Exception as e:
                logger.error(f"❌ Ошибка создания части {i+1}: {e}")
                raise

        # Создаем все части параллельно
        logger.info(f"🚀 Параллельное создание {num_parts} частей...")
        part_tasks = [create_part(i) for i in range(num_parts)]
        part_results = await asyncio.gather(*part_tasks, return_exceptions=True)

        # Проверяем результаты
        parts = []
        errors = []

        for i, result in enumerate(part_results):
            if isinstance(result, Exception):
                errors.append((i + 1, result))
            else:
                parts.append(result)

        # Если были ошибки, удаляем созданные части и выбрасываем исключение
        if errors:
            logger.error(f"❌ Ошибки при создании {len(errors)} частей из {num_parts}")
            # Удаляем все созданные части
            for part in parts:
                try:
                    os.remove(part)
                except Exception:
                    pass
            # Выбрасываем первую ошибку
            raise RuntimeError(f"Ошибки при создании частей: {errors[0][1]}") from errors[0][1]

        # Сортируем части по номеру (на случай, если порядок нарушен)
        parts.sort()

        logger.info(f"✅ Аудио разбито на {len(parts)} частей (параллельно)")
        return parts

