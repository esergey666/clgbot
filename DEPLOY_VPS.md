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
