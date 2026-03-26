# CRM-diplom

Это Django CRM-проект. Для публикации через GitHub его нужно деплоить не на GitHub Pages, а на платформу для серверных приложений, например Render.

## Что уже подготовлено

- продакшен-статические файлы через WhiteNoise;
- автоподхват хоста Render через `RENDER_EXTERNAL_HOSTNAME` и `RENDER_EXTERNAL_URL`;
- `render.yaml` для автоматического создания web service и Postgres;
- `build.sh` для миграций, загрузки стартового каталога и создания администратора;
- `Procfile` для запуска через Gunicorn;
- безопасный `.gitignore`, чтобы не отправлять в GitHub локальную БД, `venv` и случайные большие файлы.

## Что попадет в деплой

- код Django-приложения;
- стартовый каталог товаров из `core/fixtures/catalog_seed.json`;
- изображения товаров из папки `media/products`.

Локальная `db.sqlite3` намеренно не отправляется в репозиторий, потому что в ней уже есть реальные пользователи и рабочие данные.

## Переменные окружения

Для локального запуска можно взять шаблон из `.env.example`.

На Render важны:

- `SECRET_KEY`;
- `DATABASE_URL`;
- `DJANGO_SUPERUSER_USERNAME`;
- `DJANGO_SUPERUSER_EMAIL`;
- `DJANGO_SUPERUSER_PASSWORD`;
- `SERVE_MEDIA=True`.

## Как задеплоить

1. Создать пустой репозиторий на GitHub.
2. Запушить в него этот проект.
3. В Render выбрать `New +` -> `Blueprint` и подключить репозиторий.
4. Render подхватит `render.yaml`, создаст web service и Postgres.
5. При первом деплое автоматически:
   - применятся миграции;
   - загрузится стартовый каталог;
   - создастся администратор из env-переменных.

## Локальный запуск

```powershell
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver
```

## Ограничение текущего варианта

Новые файлы, загруженные в `media/` уже после деплоя, на бесплатном инстансе Render не будут храниться вечно. Для постоянного хранения пользовательских файлов потом лучше добавить S3/Cloudinary или persistent disk.
