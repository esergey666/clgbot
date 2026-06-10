# Запуск на хостинге

Проект готов к запуску на Linux-хостинге с локальным OCR.

## Переменные окружения

Обязательно:

```env
bot=токен_telegram_бота
admins=ваш_telegram_id
```

Рекомендуется для маленьких тарифов:

```env
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

Если хостинг перезапускает процесс во время распознавания фото из-за нехватки памяти, временно отключите RapidOCR:

```env
OCR_ENGINE=tesseract
```

Лучше использовать тариф с памятью от 1 GB, потому что RapidOCR и ONNXRuntime заметно тяжелее обычного Tesseract.

`OPENAI_API_KEY` не нужен. Распознавание фото работает бесплатно через RapidOCR, Tesseract OCR и OpenCV.
QR сначала читается через WeChat QR detector, затем через обычный OpenCV QR detector.

## Docker

Если хостинг поддерживает Docker, используйте текущий `Dockerfile`.

Он ставит:

- `libdmtx0b` и `libdmtx-dev` для DataMatrix;
- `tesseract-ocr` и `tesseract-ocr-eng` для запасного OCR;
- Python-зависимости из `requirements.txt`.
- WeChat QR модели из `assets/wechat_qr/`.
- RapidOCR ONNX-модели скачиваются во время Docker build.

Команда запуска внутри контейнера:

```bash
python -m bot.main
```

## Railway / Render / похожий Nixpacks-хостинг

Для Nixpacks уже настроен `nixpacks.toml`:

```toml
[phases.setup]
aptPkgs = ["libdmtx0b", "libdmtx-dev", "tesseract-ocr", "tesseract-ocr-eng"]
```

Start command:

```bash
python -m bot.main
```

## Хостинг с Aptfile или packages.txt

В `Aptfile` и `packages.txt` добавлены нужные системные пакеты:

```text
libdmtx0b
libdmtx-dev
tesseract-ocr
tesseract-ocr-eng
```

## Проверка после деплоя

1. Откройте бота в Telegram.
2. Нажмите `Создать файл`.
3. Выберите бирку.
4. Отправьте 2 фото.
5. Бот должен написать, что распознает данные локально, затем показать найденную строку.

Если бот пишет, что Tesseract не установлен, значит хостинг не применил системные пакеты. Тогда используйте Dockerfile или проверьте, что хостинг действительно читает `Aptfile`, `packages.txt` или `nixpacks.toml`.

Если QR не читается, проверьте, что на хостинг попала папка `assets/wechat_qr/` с файлами:

```text
detect.prototxt
detect.caffemodel
sr.prototxt
sr.caffemodel
```
