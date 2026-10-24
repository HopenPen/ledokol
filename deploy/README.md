# Деплой через GitLab

Сервер: Ubuntu, приложение открывается на https://194.113.106.232. Исходники GitLab: https://gitlab.com/ledokol-group/ledokol, ветка `main`.

## Как проходит обновление

1. GitLab запускает тесты backend и production-сборку frontend. Проверки выполняются также для merge request.
2. После успешных проверок **защищённой** ветки `main` job `deploy_production` отправляет `git archive` конкретного коммита по SSH. Одновременно выполняется только один деплой (`resource_group: production` и серверный `flock`).
3. Сервер распаковывает релиз в `/opt/ledokol/releases/<sha>`, собирает образы с этим SHA, сохраняет дамп существующей БД и запускает контейнеры с ожиданием healthcheck.
4. При успешной проверке `/meta/categories` обновляется `/opt/ledokol/current`. При ошибке запуска восстанавливаются контейнеры предыдущего релиза. Схема БД автоматически назад не откатывается: для несовместимых миграций нужен отдельный план восстановления из дампа.

GitLab не получает пароль root, пароль PostgreSQL или JWT-секрет. На сервере отсутствует ключ для чтения приватного GitLab-репозитория: исходники доставляет CI. Ключ CI позволяет пользователю `ledokol-deploy` выполнить только `deploy <40-значный SHA>`; интерактивный вход и перенаправление портов этим ключом закрыты.

## Настройки GitLab

Ветка `main` должна быть protected; доступ к push/merge — Maintainer. В **Settings → CI/CD → Variables** используются:

| Переменная | Тип | Protected | Значение |
|---|---|---|---|
| `DEPLOY_HOST` | Variable | Да | `194.113.106.232` |
| `DEPLOY_USER` | Variable | Да | `ledokol-deploy` |
| `SSH_PRIVATE_KEY` | File | Да | Отдельный приватный SSH-ключ CI, с переводом строки в конце |
| `SSH_KNOWN_HOSTS` | File | Да | Проверенный публичный host key сервера |

Для SSH-файлов отключено раскрытие ссылок на переменные. Многострочный приватный ключ хранится как File, не выводится в job log. Из-за ограничений GitLab на формат masked-переменных SSH-файлу может требоваться Visibility=Visible; доступ к нему ограничивают protected branch и environment scope `production`.

Нужен доступный runner с поддержкой `image:` jobs. Конфигурация рассчитана на GitLab-hosted Linux runner. Если GitLab требует Identity verification или исчерпан compute quota, владелец должен устранить ограничение и повторить pipeline. Это не останавливает уже работающий сервер. Синтаксис CI можно проверить отдельно через CI Lint.

## Файлы сервера

- `/opt/ledokol/shared/compose.env`: случайный пароль PostgreSQL и токен имитаторов.
- `/opt/ledokol/shared/app.env`: JWT-секрет, публичный URL и настройки приложения.
- `/opt/ledokol/shared/operator-access.txt`: доступ первого владельца свежей базы. Он создаётся только один раз; пароль существующего пользователя при повторном деплое не меняется.
- `/opt/ledokol/shared/data/statements/`: данные для имитатора 1С, если они нужны; датасеты с компьютера автоматически не загружаются.
- `/opt/ledokol/backups/`: дампы PostgreSQL перед обновлениями.

Секреты и резервные копии доступны только root. Данные PostgreSQL находятся в постоянном Docker volume `ledokol_pgdata`.

Почта остаётся прежней: Mailpit, без настройки внешнего SMTP и изменений подтверждения email. Порты почты доступны только на localhost сервера. Для просмотра с компьютера: `ssh -L 8025:127.0.0.1:8025 root@194.113.106.232`, затем http://localhost:8025. Из-за текущего ограничения приложения на SMTP без TLS серверный `CASHFLOW_ENV` остаётся `dev`; JWT и остальные секреты при этом случайные, приложение снаружи доступно по HTTPS. После удаления подтверждения email или подключения SMTP с TLS можно перейти на `prod`.

## Первоначальная установка

Скрипты запускаются root после проверки содержимого:

```bash
bash deploy/bootstrap-server.sh
bash deploy/configure-https.sh 194.113.106.232
bash deploy/initialize-runtime.sh https://194.113.106.232
install -m 755 deploy/deploy.sh /usr/local/sbin/ledokol-deploy
install -m 755 deploy/ssh-command.sh /usr/local/sbin/ledokol-ssh
```

Публичный ключ CI записывается в `/home/ledokol-deploy/.ssh/authorized_keys` с `restrict,command="/usr/local/sbin/ledokol-ssh"`. Приватный ключ добавляется только в защищённую CI-переменную.

HTTPS на IP выпускается Let's Encrypt через Certbot (`shortlived`, webroot). Сертификат обновляется каждые 6 часов по systemd timer `ledokol-certificate.timer`; nginx перечитывает обновлённые файлы. Порты снаружи: SSH 22, HTTP 80 (ACME и редирект), HTTPS 443. Backend, PostgreSQL и имитаторы не публикуются.

Инструкции поставщиков: [Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/), [IP-сертификаты Let's Encrypt и Certbot](https://letsencrypt.org/2026/03/11/shorter-certs-certbot), [переменные GitLab CI](https://docs.gitlab.com/ci/variables/).

## Диагностика и ручной откат

```bash
cd /opt/ledokol/current
export RELEASE_SHA=$(cat /opt/ledokol/shared/deployed-sha)
docker compose -p ledokol --env-file /opt/ledokol/shared/compose.env -f deploy/compose.yml ps
docker compose -p ledokol --env-file /opt/ledokol/shared/compose.env -f deploy/compose.yml logs --tail 100 api web
systemctl status ledokol-certificate.timer
journalctl -u ledokol-certificate.service --since yesterday
```

Для повторного деплоя запустите retry job в GitLab. Для отката выберите нужный предыдущий pipeline `main` и повторите его deploy job. Если миграция несовместима со старым кодом, сначала оцените изменения схемы и подготовьте восстановление БД из `/opt/ledokol/backups`; деплой не удаляет постоянный volume.
