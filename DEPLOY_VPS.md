# Развёртывание бота на VPS

Рекомендуемая конфигурация:

- Ubuntu 24.04;
- 2 vCPU;
- 2 ГБ RAM минимум, 4 ГБ рекомендуется;
- 20–30 ГБ SSD/NVMe;
- 2 ГБ swap при сервере с 2 ГБ RAM.

Домен, веб-сервер и открытые входящие порты боту не нужны: Telegram работает через long polling.

## Установка

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2
sudo systemctl enable --now docker
git clone https://github.com/esergey666/clgbot.git
cd clgbot
cp .env.example .env
nano .env
```

В `.env` необходимо указать:

```env
BOT_TOKEN=токен_бота_от_BotFather
ADMIN_IDS=telegram_id_администратора
OCR_ENGINE=rapidocr
```

Несколько администраторов указываются через запятую:

```env
ADMIN_IDS=123456789,987654321
```

Запуск:

```bash
sudo docker compose up -d --build
sudo docker compose logs -f --tail=100
```

## Обновление

```bash
cd clgbot
git pull
sudo docker compose up -d --build
sudo docker image prune -f
```

Пользователи, балансы и остальные рабочие данные сохраняются в каталоге `data`, подключённом к контейнеру как постоянный том.

## Полезные команды

```bash
sudo docker compose ps
sudo docker compose restart
sudo docker compose logs --tail=200
sudo docker compose down
```

Если на сервере с 2 ГБ памяти контейнер завершается во время распознавания фотографий, добавьте swap или перейдите на тариф с 4 ГБ RAM.

## ZIP-файлы больше 20 МБ

Официальный Telegram Bot API не позволяет боту скачивать файлы больше 20 МБ. Для больших ZIP используется локальный Telegram Bot API Server.

1. Получите `api_id` и `api_hash` на `https://my.telegram.org` в разделе `API development tools`.
2. Остановите основной контейнер:

```bash
sudo docker compose stop bot
```

3. Один раз отключите бота от облачного Bot API:

```bash
BOT_TOKEN_VALUE="$(sed -n 's/^BOT_TOKEN=//p' .env | tail -n 1)"
curl -sS -X POST "https://api.telegram.org/bot${BOT_TOKEN_VALUE}/logOut"
unset BOT_TOKEN_VALUE
```

Ответ должен содержать `"ok":true`. Не выполняйте этот шаг повторно при обычных обновлениях.

4. Добавьте в `.env` полученные значения:

```env
TELEGRAM_API_ID=ваш_api_id
TELEGRAM_API_HASH=ваш_api_hash
TELEGRAM_API_BASE=http://telegram-bot-api:8081
```

5. Запустите локальный API и бота:

```bash
sudo docker compose --profile local-api up -d --build
sudo docker compose --profile local-api logs -f --tail=100
```

После переключения обновляйте проект командой:

```bash
git pull
sudo docker compose --profile local-api up -d --build
```

Порт `8081` наружу не публикуется: API доступен только контейнеру бота. Данные локального Telegram API сохраняются в Docker-томе `telegram-bot-api-data`.

### Развёртывание на Bothost

Bothost запускает один контейнер и не использует `docker-compose.yml`. В проекте локальный Telegram API также встроен в основной `Dockerfile` и запускается автоматически, если заданы `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`.

В переменных окружения Bothost добавьте:

```env
TELEGRAM_API_ID=ваш_api_id
TELEGRAM_API_HASH=ваш_api_hash
TELEGRAM_API_BASE=http://127.0.0.1:8081
```

Затем включите использование Dockerfile из репозитория и выполните новый деплой. Для перехода с облачного API метод `logOut` всё равно выполняется один раз непосредственно перед первым запуском новой сборки.
