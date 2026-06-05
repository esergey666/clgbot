# checkGenerator

Бот для генерации этикетки. Функциональность оставлена прежней, код разложен по папкам для будущего расширения.

QR-код теперь генерируется через перенесенный алгоритм из отдельного проекта: `assets/maket.jpg` + матрица QR 29x29.

## Структура

```text
checkGenerator/
├── assets/              # шаблон и шрифты
│   ├── back.png
│   ├── font.ttf
│   └── num.ttf
├── bot/
│   ├── main.py          # основной запуск
│   ├── bot.py           # запуск по старому пути: python bot/bot.py
│   ├── config.py        # настройки, пути, .env
│   ├── handlers/        # обработчики Telegram-команд и сообщений
│   ├── services/        # бизнес-логика генерации картинки
│   └── states/          # FSM-состояния
├── .env.example
├── requirements.txt
└── libdmtx-64.dll
```

## Запуск

1. Создай виртуальное окружение и установи зависимости:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

2. Скопируй `.env.example` в `.env` и заполни:

```env
bot=токен_бота
admins=твой_telegram_id
```

3. Запусти:

```bash
.venv\Scripts\python.exe bot\bot.py
```

Можно также запускать так:

```bash
.venv\Scripts\python.exe -m bot.main
```
