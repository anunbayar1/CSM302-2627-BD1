# V-1-12 – Producer–Consumer Problem (Buffer Animation)

**Хичээл:** F.CSM302 Үйлдлийн систем

**Багийн код (хуваарилалтын код):** V-1-12

**Сурах бичгийн бүлэг:** 7-р бүлэг – Synchronization Examples (Silberschatz, Galvin, Gagne – Operating System Concepts, 10th ed.)

**Төслийн нэр:** Programming Project 4 – The Producer–Consumer Problem (Buffer animation UI)

## Багийн гишүүд

| Оюутны код | Нэр |
|---|---|
| B241910012 | Н.Баасандорж |
| ........... | ........... |
| ........... | ........... |
| ........... | ........... |
| ........... | ........... |

## Зорилго

Bounded buffer (цагираг дараалал)-ийг `empty` / `full` тоолох семафор болон `pthread_mutex_t`-ээр хамгаалж, C / POSIX Pthreads дээр хэрэгжүүлэх. Producer, consumer бүр тусдаа OS thread бөгөөд тэдний буфер руу бичих, буферээс уншихыг browser-based интерактив UI дээр алхам алхмаар buffer animation-оор харуулна.

## Quick Start

**Шаардлага:** Linux (Debian / Ubuntu), `gcc`, `make`, Python 3. Гадаад сан шаардлагагүй.

```
# 0. Шаардлагатай багц
sudo apt install git build-essential python3

# 1. Татах
git clone git@github.com:anunbayar1/CSM302-2627-BD1.git
cd CSM302-2627-BD1

# 2. Ажиллуулах (C программыг автоматаар compile хийж, хөтөч нээгдэнэ)
python3 src/gui.py
# → http://127.0.0.1:8765/

# 3. Тушаалын мөрөөс (номын дагуу)
make -C src/c
./src/c/producer_consumer 5 3 3      # <унтах сек> <producers> <consumers>
./src/c/producer_consumer --bug no-mutex 5 3 3   # туршилт: no-mutex | no-empty | no-full | order

# 4. Автомат тест (GUI шаардахгүй)
python3 -m unittest discover -s tests
make -C src/c test
make -C src/c tsan
```

### Windows дээр

**А. WSL2 (бүрэн ажиллагаа, C горим орно):** PowerShell-ийг администратороор нээгээд:

```
wsl --install -d Ubuntu
```

Компьютерээ дахин асаагаад **Ubuntu** терминалыг нээнэ. Тэндээ дээрх Linux-ийн 0–4-р алхмыг яг адилхан хийнэ. `http://127.0.0.1:8765/` хаягийг Windows-ийн хөтөчөөр нээнэ.

**Б. Шууд Windows дээр (зөвхөн Python · жишээтэй горим):**

1. [python.org](https://www.python.org/downloads/)-оос Python 3 суулгана (*Add python.exe to PATH*-ийг чагтална).
2. [Git for Windows](https://git-scm.com/download/win) суулгана, эсвэл GitHub дээрээс **Code → Download ZIP** хийж задлана.
3. PowerShell эсвэл Command Prompt дээр:

```
git clone git@github.com:anunbayar1/CSM302-2627-BD1.git
cd CSM302-2627-BD1
py src\gui.py
```

Энэ горимд C · Pthreads хуудас ажиллахгүй (нүүр хуудас дээр шар анхааруулга гарна), учир нь C программ POSIX семафор (`sem_timedwait`) ашигладаг. C горимыг ажиллуулахын тулд А хувилбарыг ашиглана. Python тестийг `py -m unittest tests.test_buffer` командаар ажиллуулж болно.

## Хавтасны бүтэц

| Зам | Агуулга |
|---|---|
| `src/c/` | C / Pthreads эх код: `buffer.c` (insert_item / remove_item, empty, full, mutex), `main.c` (номын CLI), `ui.c` (UI-д төлөв дамжуулах горим), `Makefile` |
| `src/gui.py` | localhost веб сервер (Python стандарт сан), C программыг удирдана |
| `src/bounded_buffer.py` | Python хэрэгжүүлэлт (шуудангийн жишээтэй горимд) |
| `src/ui/` | `home.html` (горим сонгох), `mail.html` (шуудангийн жишээ), `raw.html` (C · Pthreads), `tour.json` (дуут тайлбар) |
| `tests/` | `test_buffer.py`, `test_c.py`, `test_web.py` (нийт 42 автомат тест) |
| `docs/` | `V-1-12_Manual.pdf` – гарын авлага |
| `tools/` | `make_voice.py` – дуут тайлбарын аудио үүсгэгч (edge-tts) |

## Үндсэн боломжууд

* Нүүр хуудаснаас 2 горим сонгоно:
  * **Python · жишээтэй**: шуудан зөөгч, хэрэглэгч, шуудангийн хайрцгийн жишээгээр, монгол дуут тайлбартай.
  * **C · Pthreads**: жишээгүй, C программын бодит ажиллагаа: producers → buffer → consumers.
* BUFFER_SIZE (1–20), producer, consumer-ийн тоо (1–10), хурдыг тохируулна. Хурдыг ажиллаж байх үед ч өөрчилж болно.
* Start / Pause / Step / Stop / Reset удирдлага.
* `empty`, `full` семафорын утга, `mutex`-ийн эзэмшигч болон хүлээж буй thread-үүд, `in` / `out` заагч.
* `produced − consumed = buffer ✓` тууштай байдлын шалгалт.
* **Алдааны туршилт** (C хуудасны «алдаа» сонголт, CLI `--bug`): зөв кодоос нэг алдаа гаргаж, юу болохыг харуулна. Алдаа бүр улаанаар тэмдэглэгдэж, лог болон эцсийн дүнд гарна.

  | Сонголт | Кодын алдаа | Үр дагавар |
  |---|---|---|
  | `no-mutex` | `pthread_mutex_lock/unlock` байхгүй | race condition: хоёр thread нэг нүд рүү бичиж item алга болно |
  | `no-empty` | producer `sem_wait(&empty)` хийхгүй | overflow: уншаагүй item дээр дарж бичнэ |
  | `no-full` | consumer `sem_wait(&full)` хийхгүй | underflow: хоосон нүднээс уншина |
  | `order` | `mutex_lock` → `sem_wait` дараалал буруу | deadlock: mutex барьсан thread семафор хүлээж, бусад нь mutex хүлээнэ |
* producer / consumer sleep (0–3 сек) болон хурд (0.25–4×)-ыг гулсуураар 0.05-ын нарийвчлалтай, ажиллаж байх үед тохируулна.
* Лог-ийг `.txt` эсвэл `.csv` хэлбэрээр татаж авах.

## Баримт бичиг

* [Гарын авлага (Manual PDF)](docs/V-1-12_Manual.pdf)

## Хэрэглэсэн бэлэн код, сан, AI

* Гадаад сан ашиглаагүй: C стандарт сан + POSIX Pthreads, Python стандарт сан, vanilla HTML / CSS / JavaScript.
* Алгоритм нь сурах бичгийн 7.1.1-р хэсэг (Figures 7.1, 7.2) болон Programming Project 4-т үндэслэсэн.
* **AI:** Claude (Anthropic)-г код, автомат тест, UI болон баримт бичиг (README) боловсруулахад ашигласан.

## Мэдэгдэж буй хязгаарлалт

* C хөдөлгүүр зөвхөн Linux дээр ажиллана (`sem_timedwait`). Windows дээр WSL2 хэрэгтэй. WSL2-гүй Windows дээр зөвхөн Python горим ажиллана. macOS дээр туршаагүй.
* Mutex-ийг микросекунд л барьдаг тул UI дээр сүүлийн эзэмшигчийг ~0.5 сек харуулдаг (зөвхөн дүрслэлийн сунгалт).
* `no-mutex` туршилтад race condition-ийг харагдахуйц болгохын тулд critical section дотор түр завсар (UI: 40 мс, CLI: 0.1 мс) нэмсэн. Энэ нь thread-ийг тэр мөчид өөр thread тасалдуулсныг (preemption) дуурайлгана. Бусад горимд энэ завсар байхгүй.
* Алдаа илрүүлэхэд нүд бүрт дүүрэн / хоосон эсэхийг тэмдэглэх атомар шалгагч (`occ[]`) ашигладаг. Энэ нь алгоритмын хэсэг биш, зөвхөн хэмжилт.
* UI 50 мс тутам төлөв уншдаг тул `empty + full` түр зуур BUFFER_SIZE-аас бага харагдаж болно (thread `sem_wait`-ийн дараа, `sem_post`-оос өмнө байх үед). Энэ нь алдаа биш.
* Дуут тайлбарын аудиог `tools/make_voice.py` (интернет шаардлагатай) үүсгэнэ. Аудио байхгүй бол хөтчийн хоолойг ашиглана.
