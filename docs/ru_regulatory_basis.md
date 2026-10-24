# Нормативная база для налогового календаря и имитаторов

Собрано по открытым источникам 24.10.2026. Это не юридическая консультация: перед защитой сверить с НК РФ и nalog.gov.ru.

## Налоги и сроки МСП в 2026 году

| Что | Срок | Источник |
|---|---|---|
| ЕНП, единый срок | 28-е число; выходной → ближайший рабочий день | [Точка](https://tochka.com/knowledge/buhgalteriya/sroki-uplaty-nalogov-i-vznosov/), [Главбух: ЕНП](https://www.glavbukh.ru/art/394799-sroki-uplaty-enp-v-dekabre-2026-statgb) |
| Авансы УСН | до 28 апреля, 28 июля, 28 октября | [Главбух: календарь](https://www.glavbukh.ru/art/393855-kalendar-uplaty-nalogov-v-2026-godu-statgb) |
| УСН за год | ООО — до 28 марта, ИП — до 28 апреля | [Главбух: таблица](https://www.glavbukh.ru/art/391900-vse-sroki-uplaty-nalogov-i-vznosov) |
| НДС | ставка 22% с 01.01.2026; за квартал тремя долями до 28-го каждого из трёх следующих месяцев | [Главбух: НДС](https://www.glavbukh.ru/art/91524-sroki-uplaty-nds-tablitsa) |
| НДС на УСН | освобождение при доходе до 20 млн ₽; выше — 5% / 7% без вычетов или 22% с вычетами | [Гарант](https://www.garant.ru/1c-wiseadvice/guide/novye-stavki-nds-s-2025-goda/), [Контур](https://www.kontur-extern.ru/info/81877-usn_i_nds), [РНК](https://www.rnk.ru/article/218396-usn-2026-izmeneniya) |
| НДФЛ (агент) | удержан 1–22 → до 28-го; 23–конец месяца → до 5-го следующего; 23–31 декабря → последний рабочий день года | [РНК](https://www.rnk.ru/article/218602-kalendar-uplaty-nalogov-i-vznosov) |
| Взносы ИП за себя | фикс. 57 390 ₽ до 28.12; 1% свыше 300 тыс. ₽ до 1 июля следующего года (макс. 321 818 ₽) | [buh.ru](https://buh.ru/news/v-2026-godu-uvelichilsya-razmer-fiksirovannykh-strakhovykh-vznosov-dlya-ip.html), [Timeweb](https://timeweb.com/ru/blog/authors/ajshe/articles/strakhovyye-vznosy-ip-fiksirovannyye-platezhi-i-sroki-uplaty/) |

Не подтверждено и требует проверки: льготный тариф взносов МСП с 2026 года (по реформе 425-ФЗ сохраняется не для всех отраслей), точные пороги 5% / 7% с учётом дефлятора (встречаются 250/450 и 272,5/490,5 млн ₽), номер закона о пороге 20 млн ₽.

Что это значит для прогноза: в датасете кейса налоги идут одним ЕНП 28-го числа, поэтому модель прогнозирует ЕНП по налоговому календарю, а состав платежа (аванс УСН, треть НДС, НДФЛ) берётся из `app/domain/tax_rules.py` для подписи в интерфейсе.

## Внешние системы, которые имитируем

| Система | Как устроена в жизни | Как имитируем |
|---|---|---|
| 1С (счета, договоры) | OData `.../odata/standard.odata/Document_<Имя>?$format=json`, поля `Ref_Key` (GUID), `СуммаДокумента`, ссылки через `_Key`; точный состав полей конфигурации берётся из `$metadata` | `mocks/onec_mock.py`: те же пути и поля, постраничная выдача `odata.nextLink`, токен, задержки, 429/503. [Infostart: OData](https://infostart.ru/1c/articles/1570140/), [форум Infostart](https://forum.infostart.ru/forum15/topic272522/) |
| Клиент-банк 1С | текстовый формат `1CClientBankExchange`, `ВерсияФормата=1.03`, секции `СекцияДокумент=Платежное поручение` | TODO: эндпоинт выгрузки выписки в этом формате. [ITS 1С](https://its.1c.ru/db/content/metod8dev/src/developers/dataexchange/bankexchange/clibnkdexchange/i8103262.htm), [пример 1.03](https://forum.infostart.ru/forum15/topic293530/) |
| ФНС: реестры | ЕГРЮЛ/ЕГРИП, «Прозрачный бизнес»; официального публичного REST API нет, массовую проверку делают через коммерческие сервисы (Контур.Фокус, Checko) или старый SOAP `npchk.nalog.ru` | `mocks/fns_mock.py`: REST по ИНН — статус, долг перед бюджетом. [nalog.gov.ru: реестры](https://www.nalog.gov.ru/rn01/related_activities/registries/), [Infostart](https://infostart.ru/1c/tools/335976/) |
