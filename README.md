# Telegram AI AutoPoster

Автономный Telegram-бот для генерации и публикации изображений по расписанию.

Проект берёт идеи из `prompts.json`, выбирает один из режимов сборки промта, при необходимости прогоняет идею через OpenAI-compatible LLM, генерирует изображение через `diffusers`, опционально проверяет результат на вероятный текст / водяные знаки и публикует пост в Telegram-канал. После перезапуска бот продолжает работу и сначала пытается допубликовать уже сгенерированные, но ещё не отправленные изображения.

Эта версия README подготовлена для публикации на GitHub и приведена в соответствие с реальной конфигурацией проекта: базовая модель — `cagliostrolab/animagine-xl-4.0`, режим выбора промтов — `AB_RANDOM`, разрешение — случайное из пресетов, LLM подключается через OpenAI-compatible endpoint.

---

## Что умеет проект

- автопостинг в Telegram по таймеру;
- генерация изображений через `diffusers` + Hugging Face model id или локальный путь к модели;
- поддержка режимов выбора промтов:
  - `A` — одна идея;
  - `B` — контентная идея + модификатор;
  - `AB_RANDOM` — случайный выбор между `A` и `B`;
- опциональное расширение / склейка промтов через OpenAI-compatible LLM;
- подстановка `{{subj1}}`, `{{subj2}}`, `{{subj3}}` из отдельных текстовых файлов;
- защита от повторов по истории последних использованных prompt ID;
- сохранение истории генераций и runtime-настроек в SQLite;
- попытка допубликовать `pending/generated` результат после рестарта;
- фильтрация по вероятному тексту / водяным знакам:
  - `off` — выключено;
  - `fast` — быстрая эвристика;
  - `strict` — эвристика + OCR;
- админ-команды в Telegram для паузы, принудительного постинга, смены интервала и модели;
- случайный выбор разрешения из списка пресетов.

---

## Как это работает

1. Загружается конфигурация из `.env`.
2. Создаются нужные каталоги и поднимается SQLite-база.
3. Промты из `prompts.json` импортируются в БД.
4. Планировщик запускает цикл публикации каждые `POST_INTERVAL_MIN` минут.
5. На каждом цикле бот:
   - сначала пытается отправить ранее сгенерированное, но не опубликованное изображение;
   - выбирает prompt card из банка;
   - собирает финальный промт в режиме `A` или `B`;
   - при активной LLM дорабатывает строку промта;
   - автоматически добавляет `ANIMAGINE_RATING`, если он задан и ещё не присутствует в промте;
   - генерирует изображение через `diffusers`;
   - при необходимости прогоняет результат через фильтр;
   - публикует изображение в канал;
   - сохраняет статус, хэш файла и историю в SQLite.

---

## Стек

- Python 3.11
- aiogram 3
- APScheduler
- diffusers
- PyTorch
- SQLite
- Pillow / OpenCV
- python-dotenv
- httpx
- опционально: `pytesseract` + системный `tesseract`

---

## Структура проекта

```text
app/
  config.py                 # загрузка и валидация .env
  main.py                   # точка входа
  pipeline.py               # основной цикл генерации и публикации
  image_gen/
    sd_generator.py         # Diffusers pipeline + генерация PNG
  image_filter/
    watermark_fast.py       # быстрая эвристика текста / watermark
    watermark_strict.py     # OCR-проверка
  prompt_bank/
    loader.py               # загрузка prompts.json
    prompt_bank.py          # импорт prompt ideas в SQLite
    topic_selector.py       # выбор карточек для Mode A / Mode B
  prompt_expander/
    expander.py             # subject slots + финальная сборка промта
    llm_adapter.py          # OpenAI-compatible LLM adapter
  publisher/
    publisher.py            # публикация в Telegram
  scheduler/
    scheduler.py            # APScheduler service
  storage/
    db.py                   # SQLite-обёртка
    migrations.py           # миграции схемы
  telegram_bot/
    bot.py                  # создание бота / dispatcher
    handlers.py             # админ-команды
requirements.txt
README.md
```

---

## Требования

### Минимально

- Python **3.11**
- Telegram Bot Token
- Telegram-канал, куда бот добавлен администратором
- GPU с CUDA для комфортной генерации SDXL-моделей

### Рекомендуемо

- Windows 11 или Linux
- CUDA-совместимый PyTorch
- от 8 ГБ VRAM для SDXL-подобных моделей
- быстрый SSD под `HF_HOME`

---

## Установка

### 1. Клонирование репозитория

```bash
git clone <your-repo-url>
cd <repo-folder>
```

### 2. Создание виртуального окружения

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### 3. Установка зависимостей проекта

```bash
pip install -r requirements.txt
```

### 4. Установка PyTorch под CUDA

Подставь свою сборку CUDA. Пример для CUDA 12.1:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 5. Опционально: OCR для strict-фильтра

Если хочешь использовать `WATERMARK_MODE=strict`, установи:

```bash
pip install pytesseract
```

И отдельно поставь системный `tesseract`.

### 6. Создание `.env`

Скопируй шаблон:

```bash
cp .env.example .env
```

На Windows можно просто создать `.env` вручную на основе шаблона.

### 7. Подготовка данных

Создай или проверь наличие файлов:

- `data/prompts.json`
- `data/subjects_1.txt`
- `data/subjects_2.txt`
- `data/subjects_3.txt`

Если subject-файлы отсутствуют, проект подставит fallback-значения.

### 8. Запуск

```bash
python -m app.main
```

---

## Настройка Telegram

1. Создай бота через **@BotFather**.
2. Получи `BOT_TOKEN`.
3. Добавь бота в канал.
4. Выдай ему права администратора.
5. Укажи `CHANNEL_ID` в `.env`.
6. Укажи свои Telegram ID в `ADMIN_IDS` через запятую.

Пример:

```env
BOT_TOKEN=123456:ABCDEF...
CHANNEL_ID=@my_channel
ADMIN_IDS=123456789,987654321
```

---

## Конфигурация `.env`

Ниже — актуальная логика конфигурации проекта.

### Telegram

```env
BOT_TOKEN=
CHANNEL_ID=
ADMIN_IDS=
TG_SEND_AS=photo
CAPTION_TEMPLATE=
```

- `TG_SEND_AS=photo` — Telegram пережимает изображение.
- `TG_SEND_AS=document` — отправка без пережатия, если нужен оригинальный PNG.
- `CAPTION_TEMPLATE` — подпись к посту. Можно оставить пустым.

### Пути

```env
DATA_DIR=./data
OUTPUT_DIR=./data/outputs
DB_PATH=./data/db/app.db
HF_HOME=./data/hf_cache
PROMPTS_PATH=./data/prompts.json
```

### Планировщик

```env
POST_INTERVAL_MIN=20
PAUSED=false
```

- `POST_INTERVAL_MIN` — интервал между циклами.
- `PAUSED=true` — старт в режиме паузы.

### Выбор промтов

```env
PROMPT_MODE=AB_RANDOM
PROMPT_MODE_A_WEIGHT=0.5
MODIFIER_TOPIC_REGEX=(?i)^(camera settings|lighting)$
NO_REPEAT_LAST_N=20
```

- `PROMPT_MODE=A` — только одна идея.
- `PROMPT_MODE=B` — контент + модификатор.
- `PROMPT_MODE=AB_RANDOM` — случайный выбор между A и B.
- `PROMPT_MODE_A_WEIGHT` — вероятность режима A в `AB_RANDOM`.
- `MODIFIER_TOPIC_REGEX` определяет, какие темы считаются модификаторами для режима B.
- `NO_REPEAT_LAST_N` — защита от повторного использования последних prompt ID.

### Генерация через diffusers

```env
MODEL_ID=cagliostrolab/animagine-xl-4.0
ANIMAGINE_RATING=explicit
DTYPE=float16
SAMPLER=euler_a
STEPS=30
CFG=7.0
RESOLUTION_MODE=random
RESOLUTION_PRESETS=1024x1024,1344x768,768x1344
WIDTH=512
HEIGHT=768
SEED=
NEGATIVE_DEFAULT=lowres, blurry, text, watermark, logo, worst quality, bad anatomy, censorship
```

Что важно:

- по умолчанию проект настроен под **Animagine XL 4.0**;
- `ANIMAGINE_RATING=explicit` автоматически добавляется в начало промта, если тега ещё нет;
- `SAMPLER=euler_a` переключает scheduler в `EulerAncestralDiscreteScheduler`;
- `RESOLUTION_MODE=random` берёт случайное разрешение из `RESOLUTION_PRESETS`;
- `WIDTH` / `HEIGHT` используются как fallback, если пресеты не заданы или `RESOLUTION_MODE=fixed`;
- пустой `SEED` означает случайный seed;
- `NEGATIVE_DEFAULT` добавляется как базовый negative prompt.

Поддерживаемые sampler-значения в текущем коде:

- `euler_a`
- `euler`
- `dpmpp_2m` / `dpmpp` / `dpm`
- `ddim`

### Фильтрация

```env
WATERMARK_MODE=off
REJECT_IF_TEXT_LIKELY=false
NSFW_FILTER_ENABLED=false
```

- `WATERMARK_MODE=off` — фильтр выключен.
- `WATERMARK_MODE=fast` — быстрая эвристика.
- `WATERMARK_MODE=strict` — эвристика + OCR.
- `REJECT_IF_TEXT_LIKELY=true` — отклонять изображение при подозрении на текст / watermark.
- `NSFW_FILTER_ENABLED` сейчас предусмотрен в конфиге, но по умолчанию выключен.

### Subject slots

```env
SUBJECTS_1_PATH=./data/subjects_1.txt
SUBJECTS_2_PATH=./data/subjects_2.txt
SUBJECTS_3_PATH=./data/subjects_3.txt
```

Поддерживаются плейсхолдеры:

- `{{subj1}}`
- `{{subj2}}`
- `{{subj3}}`

Формат строк в subject-файлах:

```text
3|1girl
1|solo female character
2|anime girl
```

Слева — вес, справа — текст. Если вес не указан, используется `1`.

### LLM adapter

```env
LLM_MODE=openai_compatible
LLM_BASE_URL=http://127.0.0.1:1234
LLM_API_KEY=local
LLM_MODEL=dolphin3.0-llama3.1-8b
```

- `LLM_MODE=openai_compatible` — проект использует endpoint формата `/v1/chat/completions`.
- Подходит для LM Studio, OpenAI-compatible прокси и других совместимых локальных / удалённых серверов.
- Если LLM отключить, проект продолжит работать без переписывания промтов.

Чтобы отключить LLM:

```env
LLM_MODE=none
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
```

---

## Формат `prompts.json`

Поддерживаемая структура:

```json
{
  "Face Expressions": {
    "Shocked": "{{subj1}}, shocked, open mouth, ...",
    "Angry": [
      "{{subj1}}, angry, red face, ...",
      "{{subj2}}, angry, narrowed eyes, ..."
    ]
  },
  "Camera Settings": {
    "Close-up": "close up, portrait composition, ..."
  },
  "Lighting": {
    "Soft light": "soft light, ambient lighting, ..."
  }
}
```

Правила:

- верхний уровень — `topic`;
- внутри — `subtopic`;
- значение — либо строка, либо список строк;
- каждая строка становится отдельной `prompt idea`;
- ID промта считается по `topic + subtopic + text`;
- темы, совпадающие с `MODIFIER_TOPIC_REGEX`, считаются модификаторами для режима `B`.

---

### Где хранится модель

По умолчанию проект использует Hugging Face model id:

```env
MODEL_ID=cagliostrolab/animagine-xl-4.0
HF_HOME=./data/hf_cache

---

## Админ-команды

Команды доступны только пользователям из `ADMIN_IDS`.

- `/status` — текущее состояние, интервал, следующий запуск, прогресс генерации, последние ошибки;
- `/post_now` — немедленно выполнить один цикл;
- `/pause` — поставить автопостинг на паузу;
- `/resume` — снять с паузы;
- `/set_interval <minutes>` — изменить интервал между постами;
- `/set_model <hf_model_id_or_path>` — сменить модель генерации;
- `/reload_prompts` — перечитать `prompts.json`;
- `/help` — список команд.

Примеры:

```text
/set_interval 60
/set_model cagliostrolab/animagine-xl-4.0
/reload_prompts
```

---

## Как хранится состояние

Проект использует SQLite для:

- списка импортированных prompt ideas;
- истории генераций;
- статусов `generated / posted / rejected / error`;
- runtime-настроек, изменённых через Telegram-команды.

Это значит, что после перезапуска бот:

- помнит паузу / интервал / модель, если они были изменены через команды;
- может сначала допостить уже готовое изображение, а не генерировать новое.

---

## Примечания по производительности

Для слабых GPU можно снизить нагрузку так:

```env
DTYPE=float16
STEPS=20
CFG=6.5
RESOLUTION_MODE=fixed
WIDTH=768
HEIGHT=1024
```

Если VRAM мало, можно попробовать:

- уменьшить разрешение;
- уменьшить `STEPS`;
- отключить LLM, если он расположен на той же машине и нагружает систему;
- использовать более лёгкую модель или локальный путь к уже скачанной модели.

---

## Публикация на GitHub

Для публичного репозитория лучше выкладывать:

- код проекта;
- `README.md`;
- `.env.example` без секретов;
- безопасный пример `prompts.json`.

Не публикуй в GitHub:

- реальный `.env`;
- токены и ключи;
- приватные endpoint-адреса, если не хочешь светить инфраструктуру;
- чувствительные / спорные prompt packs.

---

## Лицензирование

Если хочешь разрешить использование кода с обязательным сохранением авторства, удобная схема такая:

- код: `Apache-2.0`
- документация / prompt presets / non-code content: `CC BY 4.0`

Такой вариант подходит для GitHub-репозитория и нормально читается пользователями.

---

## Запуск

```bash
python -m app.main
```

Если бот настроен правильно, он поднимет БД, импортирует промты, запустит планировщик и начнёт публиковать изображения в Telegram-канал по заданному интервалу.
