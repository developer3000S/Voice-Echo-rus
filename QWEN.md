# QWEN.md - Обзор проекта Voice Echo

Последнее обновление: 8 сентября 2026 г.

Этот файл предоставляет обзор структуры и ключевых компонентов проекта Voice Echo. Он предназначен для использования в качестве инструкционного контекста для будущих взаимодействий.

## Обзор проекта

Voice Echo — это open-source настольный ИИ-ассистент для Windows, сочетающий голосовое и текстовое управление с автоматизированными рабочими процессами, осведомлённостью о содержимом экрана и генерацией разнообразного контента. Разработанный для продвинутой продуктивности на рабочем столе, Voice Echo предоставляет голосовое управление и автоматизацию рабочего стола, управление приложениями, браузерные рабочие процессы, работу с файлами, контекстный осмотр экрана, адаптивное выполнение задач, генерацию презентаций/документов/отчётов и дистанционное управление через Discord и Voice Connect.

## Ключевые возможности

### Интеллектуальный ассистент

- Единая обработка голосовых и текстовых команд
- Слушание ключевого слова пробуждения («Voice Echo») и отзывчивая активация ассистента
- Динамический осмотр экрана для контекстных ответов
- **Офлайновый локальный голос** (Vosk/sherpa STT + Piper TTS, без зависимости от Google)
- **Единый Gemini Native Voice** для всех системных оповещений и ежедневных брифингов
- **Настоящее прерывание (Barge-in)** с динамическим шумоподавлением
- **Проактивный движок** для спонтанного, контекстного взаимодействия в режиме ожидания
- ИИ на базе Gemini с устойчивым резервированием через OpenRouter

### Продуктивность и автоматизация

- **Менеджер состояния системы и ресурсов** — мониторинг CPU/RAM и принудительное закрытие зависших приложений
- **Фоновые мониторы и оповещения** — автономный опрос цен криптовалют, потребления RAM/CPU или работоспособности сайтов
- **Анализатор буфера обмена** — мгновенное чтение и обработка скопированного текста
- Открытие и управление приложениями Windows, окнами, файлами и системными действиями
- Автоматизация браузера с рабочими процессами на базе Playwright
- Контекстная автоматизация на основе содержимого экрана и уведомлений
- **ИИ-ассистент Instagram** — опрос Direct-сообщений, уведомления и бесшовный перехват чатов или ответ
- Напоминания, помощь в организации встреч и управление уведомлениями

### Документы и офисные инструменты

- Генерация презентаций, сводок и содержимого слайдов
- Создание документов Word и таблиц из промптов
- Экспорт оформленных отчётов и материалов в PDF
- Локальная сборка целевых страниц и веб-пространств

### Интеграции

- Мост Instagram Direct для чтения и автоответа на сообщения
- Мост Discord для дистанционных команд и совместной работы
- Резервирование OpenRouter для непрерывного доступа к ИИ
- Настраиваемые параметры голоса, интерфейса, запуска и уведомлений
- Voice Connect для обнаружения устройств и маршрутизации команд

## Технологический стек

| Уровень | Технология |
|---|---|
| Язык | Python 3.11/3.12 |
| Фреймворк UI | PyQt6 (кастомная гласмorfic тёмная тема) |
| Основной ИИ | Google Gemini 2.5 Flash (Native Audio) |
| Резервный ИИ | OpenRouter (40+ бесплатных моделей) |
| Локальный ИИ | Ollama/LM Studio через совместимый с OpenAI API |
| Автоматизация браузера | Playwright |
| Умный дом | TP-Link Kasa, Philips Hue, LG ThinQ, Daikin, Tuya, Nest, SmartThings, Atomberg |
| Голос (онлайн) | sounddevice + PyAudio, Gemini Live Audio |
| Голос (офлайн) | Vosk/sherpa-onnx (STT) + Piper (TTS) через `local_voice.py` |
| Буфер обмена | pyperclip |
| Захват экрана | mss + OpenCV + MediaPipe |
| Управление рабочим столом | pyautogui, pygetwindow, psutil, comtypes, pycaw |
| Discord | discord.py |
| Instagram | instagrapi |
| Генерация документов | python-pptx, python-docx, openpyxl, reportlab |
| Бэкенд | FastAPI + Uvicorn (сервер панели) |
| Конфигурация | JSON-файлы в `config/` |

## Структура проекта

```
Voice-Echo-rus/
├── main.py                  # App startup, AI orchestration, command routing (3433 lines)
├── ui.py                    # Qt desktop interface (12933 lines)
├── local_voice.py           # Offline STT/TTS engine (Vosk/sherpa + Piper) and voice loop
├── download_voice_models.py # Fetches offline models into config/models/
├── smart_home_page_new.py   # Smart home dashboard page
├── discord_bot.py           # Discord bridge service
├── llm_client.py            # Unified AI client (Local/OpenRouter)
├── or_client.py             # OpenRouter client with fallback pool
├── plugin_manager.py        # Plugin loader with hook dispatch
├── updater.py               # GitHub fast-forward updater
├── gesture_utils.py         # Gesture detection for camera
├── workspace_store.py       # Workspace/memory persistence
├── bootstrap.ps1            # Windows admin bootstrap installer
├── start_voice.bat/.vbs    # Launch shortcuts
├── requirements.txt         # Python dependencies
├── actions/                 # Modular automation tools (~35 modules)
│   ├── attention_monitor.py # Wake-word, screen awareness, proactive engine
│   ├── background_monitor.py# Crypto/system/website monitors
│   ├── browser_control.py   # Playwright browser automation
│   ├── clipboard_processor.py
│   ├── computer_control.py
│   ├── computer_settings.py # Brightness, volume, Wi-Fi, lock, shutdown
│   ├── daily_briefing.py
│   ├── dev_agent.py         # Autonomous coding agent
│   ├── docx_tools.py        # Word document generation
│   ├── file_controller.py   # File/folder operations
│   ├── file_processor.py
│   ├── flight_finder.py
│   ├── instagram_chat.py    # Instagram DM bridge
│   ├── meeting_assistant.py
│   ├── office_builder.py    # PPTX/XLSX generation
│   ├── open_app.py
│   ├── pdf_tools.py
│   ├── proactive.py         # Proactive interaction engine
│   ├── screen_processor.py
│   ├── send_message.py
│   ├── system_manager.py
│   ├── web_search.py
│   ├── weather_report.py
│   └── website_builder.py
├── agent/                   # Autonomous agent components
│   ├── error_handler.py
│   ├── executor.py
│   ├── planner.py
│   └── task_queue.py
├── voice_connect/          # Local network device discovery & control
│   ├── agents/
│   ├── gateway/
│   ├── service.py
│   └── README.md
├── voice-connect-android/  # Android companion app
├── config/                  # Settings & credentials (gitignored)
│   ├── api_keys.json
│   ├── app_settings.json
│   ├── voice_connect.json
│   ├── voice_connect/
│   ├── models/
│   └── create_desktop_shortcut.ps1
├── core/                    # Core infrastructure
│   ├── identity.py          # Assistant/owner identity management
│   ├── prompt.txt           # System prompt template
│   └── updater.py
├── dashboard/               # FastAPI dashboard server
│   ├── server.py
│   └── static/
├── extra/                   # Experimental/utility scripts
├── memory/                  # Memory manager (short/long-term)
│   └── memory_manager.py
├── plugins/                 # Plugin extensions (hooks: on_voice_created, on_startup, on_text_command)
├── smart_home/              # Smart home service & providers
│   ├── service.py
│   ├── smart_device_manager.py
│   ├── storage.py
│   └── providers/
├── tests/                   # Integration tests
│   ├── conftest.py
│   ├── test_voice_connect.py
│   ├── test_voice_connect_actions.py
│   ├── test_gesture_utils.py
│   └── test_screen_processor.py
├── homescreen background/   # Next.js homescreen web app
│   ├── app/, components/, lib/
│   ├── next.config.ts
│   └── package.json
├── assets/                  # Images, logos, web background
└── auth/                    # Authentication module
```

## Основная архитектура

### VoiceLive (main.py:1449)

Центральный класс оркестрации. Обеспечивает:
- Голосовой ввод через `sounddevice` (отправка 16 кГц, приём 24 кГц)
- Gemini Native Voice LLM с резервированием через OpenRouter
- **Офлайновый голосовой цикл**: когда `local_voice_engine` включён в настройках, пропускает цикл подключения Gemini Live и запускает `LocalVoiceEngine` (sherpa/Vosk STT → маршрутизатор команд) с Piper TTS для всех голосовых ответов
- Маршрутизация команд к обработчикам инструментов
- Извлечение памяти и построение контекста
- Генерацию плана задач для каждого типа запроса
- Режим холостого/проактивного взаимодействия
- Осмотр экрана/окон
- Режим встреч с поддержкой перехвата
- Мониторинг Direct-сообщений Instagram и поток ответов
- Мониторинг внимания (звонки, сообщения)
- Диспетчеризацию команд умного дома
- Команды устройств Voice Connect

### LocalVoiceEngine (local_voice.py)

Офлайновый, независимый от Google голосовой путь (включён по умолчанию):
- `LocalSTT` — streaming Zipformer на базе sherpa-onnx (`sherpa-onnx-streaming-zipformer-small-ru-vosk`), VAD с обнаружением тишины/конца фразы, фильтрация по ключевому слову пробуждения
- `LocalTTS` — нейронный русский голос Piper (`ru_RU-irina-medium`), int16 → воспроизведение через sounddevice с защитой от эха (нет транскрипции во время работы TTS)
- Отправка распознанных фраз через `ui.submit_external_command(text, "local")` в фоновом потоке

### VoiceUI (ui.py:10713 / 12205)

Главное окно Qt с:
- Гласмorfic тёмной темой (золотой акцент `#ffb300`, динамически перекрашиваемый)
- Фоновым виджетом с анимированным фоном WebEngine или статическим изображением
- Оверлеем удалённого ключа с QR-кодом для сопряжения с телефоном
- Отображением системных метрик
- Предпросмотром камеры жестов
- HUD-холстом с индикаторами
- Пузырьками сообщений/задач/вложений/событий/артефактов/чатов
- Боковой панелью рабочего пространства, встроенным чатом, панелью управления лаунчером
- Центром настроек, страницей системных подключений
- Разделом умных устройств
- Последовательностью загрузки, сканирования, входящих оповещений и оверлеями встреч
- Плавающим лаунчером и карточкой жестов

### UnifiedAIClient (llm_client.py)

Независимый от провайдера ИИ-клиент:
- `chat()` — текстовое дополнение с маршрутизацией Local/OpenRouter
- `chat_json()` — структурированный вывод JSON
- `vision()` — анализ изображений из base64
- `vision_from_file()` — анализ изображений по пути к файлу
- `multi_turn()` — поддержка истории разговора
- Резервирование через OpenRouter при сбое локального ИИ

### OpenRouterClient (or_client.py)

Клиент API OpenRouter с:
- 30+ текстовыми моделями + 9 моделями зрения в пуле резервирования
- Отслеживание лимита запросов с 60-секундным периодом восстановления
- Логикой повторных попыток (2 попытки на модель, задержка 2 с)
- Режимом JSON с удалением разметки
- `vision_from_file()` для анализа изображений из файлов

### Система плагинов

`plugin_manager.py` загружает `.py` файлы из `plugins/` и диспетчизирует хуки:
- `on_voice_created(voice)` — при инициализации экземпляра ассистента
- `on_startup(voice)` — после запуска при регистрации плагинов
- `on_text_command(text, source, voice=None)` — для каждой входящей текстовой команды; верните `True`, чтобы указать обработку

### Система памяти

`memory/memory_manager.py` — краткосрочная и долгосрочная память с извлечением, форматированием и построением контекста для запросов.

## Запуск приложения

```powershell
# Manual start
python main.py

# Clean startup (Windows)
start_voice.vbs

# Bootstrap installer (admin, installs Python + Node + venv + deps)
bootstrap.ps1

# Quick setup
python setup.py
```

## Соглашения разработки

- **Монолитная архитектура**: Основная логика находится в `main.py` и `ui.py` (крупные файлы, намеренно объединённые)
- **Инструменто-ориентированный дизайн**: Всегда вызывайте соответствующий инструмент, а не имитируйте результаты
- **Цепочка резервирования Gemini**: Gemini Native Audio → текстовый Gemini → OpenRouter → локальный ИИ
- **Офлайновый голос по умолчанию**: при `local_voice_engine: true` в `config/app_settings.json` голосовой цикл полностью локальный (Vosk/sherpa + Piper), и Gemini никогда не используется для распознавания речи
- **JSON-конфигурация**: Все настройки хранятся в `config/*.json` (секреты исключены из git)
- **Без коммита секретов**: `config/api_keys.json` и `config/discord_bot.json` находятся в `.gitignore`
- **Виртуальное окружение**: Требуется для всей разработки и выполнения (`.venv/` в `.gitignore`)
- **Ориентация на Windows**: Некоторые пути жёстко задают расположения для Windows (например, `pythonw.exe` в `ui.py`)
- **Тестирование**: `pytest` с `conftest.py` для настройки путей; тесты в `tests/`
- **Хуки плагинов**: Верните `True` из `on_text_command`, чтобы указать, что команда обработана, и остановить распространение

## Файлы конфигурации

| Файл | Назначение |
|---|---|
| `config/api_keys.json` | Ключи API Gemini и OpenRouter |
| `config/app_settings.json` | Параметры голоса, интерфейса, запуска и автоматизации |
| `config/voice_connect.json` | Настройки сопряжения устройств, шлюза и обнаружения |
| `config/discord_bot.json` | Учётные данные моста Discord (исключены из git) |
| `config/models/` | Офлайновые голосовые модели (Piper + Vosk/sherpa, исключены из git) |
| `core/prompt.txt` | Шаблон системного промпта, загружаемый при запуске |
| `core/identity.py` | Динамическая вставка идентификации (имя ассистента, владелец, роль, режим) |

## Известные особенности

- **Крупные файлы**: `main.py` (3,4 тыс. строк) и `ui.py` (12,9 тыс. строк) намеренно объединённые; рефакторинг в меньшие модули не входит в_SCOPE, если это не запрошено явно
- **Зависимость от Windows**: `start_voice.vbs`, `bootstrap.ps1` и некоторые пути в `ui.py` предполагают Windows; поддержка Linux/macOS ограничена
- **Требуется ключ API Gemini**: Основной провайдер ИИ; OpenRouter используется только как резервирование без Gemini
- **Браузеры Playwright**: Необходимо запустить `playwright install` после `pip install -r requirements.txt`

## Сообщество и поддержка

- Discord: https://discord.gg/gEYmJKKtq3
- GitHub: https://github.com/titechprabhasolutions/Voice-AI---Lite.git

## Лицензия

Пользовательская лицензия с доступным исходным кодом. Подробности см. в `LICENSE`.

## Ответственный

Suryaansh Tiwari

> Сохраняйте атрибуцию и держите учётные данные в безопасности при разработке на базе Voice Echo.
