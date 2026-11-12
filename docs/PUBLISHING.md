# Публикация PhiloLoom на GitHub Pages

После вливания PR с `.github/workflows/pages.yml` зайди в **Settings → Pages → Build and deployment** и выбери **GitHub Actions**. При следующем push в `main` (или вручную через Actions → Build and deploy PhiloLoom → Run workflow) GitHub установит зависимости, выполнит `make check` и опубликует `dist/`.

До подключения домена адрес проекта будет: https://mksddn.github.io/philoloom/

## Свой домен

1. Купи домен у любого регистратора. Не нужно покупать хостинг: GitHub Pages размещает статический сайт сам.
2. В **Settings → Pages → Custom domain** сначала добавь домен и сохрани. Рекомендуется предварительно подтвердить владение доменом в GitHub (Settings → Pages → Verify a domain).
3. Затем в DNS-панели регистратора создай нужные записи:

Для корневого домена (например, `example.com`):

| Type | Host | Value |
| --- | --- | --- |
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | mksddn.github.io |

Для адреса `www.example.com`: CNAME для `www` → `mksddn.github.io`. Можно также настроить A-записи корня, чтобы GitHub перенаправлял с `example.com` на `www.example.com`.

4. Дождись проверки DNS в Settings → Pages, затем включи **Enforce HTTPS**, когда опция станет доступна. DNS-изменения могут распространяться до 24 часов.

**Важно:** CNAME указывает на `mksddn.github.io`, **не** на `mksddn.github.io/philoloom`. При публикации через GitHub Actions домен задаётся в настройках Pages, а не через файл `CNAME` внутри `dist`. Не создавай wildcard DNS-записей (`*`). Не направляй DNS на GitHub до указания домена в настройках репозитория.

Подробности: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site

## Что публикуется

Все записи исходного Notion, включая раздел «Самостоятельная работа», сейчас предназначены для открытого сайта. GitHub-репозиторий тоже публичный: **не добавляй в него личные заметки, секреты, учебные оценки или другие данные, которые не хочешь публиковать**. Исключение записи из визуального интерфейса не скрывает её исходник из публичного Git.

Перед запуском проверь опубликованные данные и авторские права на тексты/изображения. Для приватных учебных заметок используй отдельный приватный репозиторий, а не `content/notion/`.
