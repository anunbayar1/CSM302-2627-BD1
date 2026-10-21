# Producer-Consumer Problem (bounded buffer)
- Course: F.CSM302 Operating Systems, BD1
- Code: V-1-12 | Topic: The Producer-Consumer Problem (OS Concepts ch.7)
- Team: B222230020, B232270028, B241910012, B241910035, B242270014

Bounded circular buffer with `empty`/`full` semaphores and a `mutex`;
`insert_item()` / `remove_item()` return 0 on success, -1 on error.
Tkinter UI animates buffer slots, in/out pointers, semaphore values and
producer/consumer states (sleeping / producing / waiting / consuming / paused).

## Quick Start (Python 3.8+, no external packages)
```
git clone <repo-url> && cd producer_consumer
python src/gui.py                               # interactive UI
python src/bounded_buffer.py 10 3 3 5 0.5       # CLI: 10 s, 3 prod, 3 cons, buffer 5, max sleep 0.5 s
python -m unittest discover -s tests -v         # tests
```
Linux may need `sudo apt install python3-tk`.

## Layout
`src/` code, `tests/` tests, `docs/` Manual + screenshots.

## Third-party code / AI use
