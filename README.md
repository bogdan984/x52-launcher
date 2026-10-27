# X52 Launcher

Программа для джойстика **Saitek / Logitech X52** под Windows 10/11: профили кнопок, макросы и последовательности, мини-стик как правый стик виртуального геймпада Xbox 360 (для обзора в DCS World), автопереключение профилей под игру. Поддерживаются DCS World, War Thunder, IL-2 и ACE COMBAT 8.

Интерфейс на русском языке. Английский будет позже.

## Установка

1. Скачайте `X52_Launcher_Setup_<версия>.exe` в разделе [Releases](../../releases/latest).
2. Запустите установщик. Если у вас его нет, отметьте драйвер **ViGEmBus**: без него не работает виртуальный геймпад.
3. Подробная настройка описана в `README.txt` и `MANUAL.txt`. Обе инструкции ставятся вместе с программой.

### Предупреждение Windows / антивируса

Exe не подписан цифровой подписью: подпись платная. Поэтому:
- SmartScreen покажет «Неизвестный издатель». Нажмите «Подробнее» → «Выполнить в любом случае».
- Некоторые антивирусы ложно срабатывают на программы, собранные PyInstaller. Установщик собирается автоматически из этого исходного кода в GitHub Actions, и процесс сборки открыт ([workflow](.github/workflows/release.yml)).

## Запуск из исходников

Нужен Python 3.13 для Windows:

```
pip install -r requirements.txt
python x52_ac8_launcher.py
```

Тесты (работают и на Linux, для окон нужен виртуальный дисплей):

```
pip install pytest pygame==2.6.1
xvfb-run -a python -m pytest -q
```

## Выпуск новой версии

Поднимите `APP_VERSION` в `x52_ac8_launcher.py` и поставьте тег с той же версией:

```
git tag v5.5.24 && git push origin v5.5.24
```

GitHub Actions соберёт установщик на Windows и выложит его в Releases.

## Авторы

bogdan984. Код написан вместе с Claude (Anthropic).

## Лицензия

[MIT](LICENSE). Сторонние компоненты перечислены в [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
