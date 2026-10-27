# Producer–Consumer (OS Concepts ch.7, Programming Project 4) — Pthreads
#   make                     build ./producer_consumer (BUFFER_SIZE = 5)
#   make BUFFER_SIZE=10      build with another buffer size
#   make run                 5 s, 3 producers, 3 consumers
#   make test                normal, boundary and error cases (+ race without the mutex)
#   ./producer_consumer --bug no-mutex|no-empty|no-full|order 5 3 3   experiments (errors reported)
#   make tsan                build with ThreadSanitizer (data-race check)
CC      ?= gcc
CFLAGS  ?= -Wall -Wextra -O2 -std=c11 -D_DEFAULT_SOURCE
LDFLAGS += -pthread
BUFFER_SIZE ?= 5
BIN     = producer_consumer
SRC     = main.c buffer.c ui.c

$(BIN): $(SRC) buffer.h sim.h
	$(CC) $(CFLAGS) -pthread -DBUFFER_SIZE=$(BUFFER_SIZE) -o $@ $(SRC) $(LDFLAGS) -lm

run: $(BIN)
	./$(BIN) 5 3 3

tsan: $(SRC) buffer.h sim.h
	$(CC) -g -O1 -std=c11 -D_DEFAULT_SOURCE -fsanitize=thread -pthread -DBUFFER_SIZE=$(BUFFER_SIZE) -o $(BIN)_tsan $(SRC) -lm
	./$(BIN)_tsan -q 2 8 8 0.01
	(printf 'tune 0.01 0.01 4\n'; sleep 1; printf 'pause\nstep\nstep\nresume\n'; sleep 1; printf 'stop\n') | ./$(BIN)_tsan --ui 3 6 6 1 1 1 0 | tail -1

test: $(BIN)
	@echo "== normal cases (must print CONSISTENT, exit 0)"
	./$(BIN) -q 2 1 1 0.05
	./$(BIN) -q 2 3 3 0.05
	./$(BIN) -q 2 8 1 0.05
	./$(BIN) -q 2 1 8 0.05
	./$(BIN) -q 2 20 20 0
	@echo "== experiments: each classic mistake must be detected"
	./$(BIN) -q --bug no-mutex 1 8 8 0; test $$? -eq 2
	./$(BIN) -q --bug no-empty 1 4 1 0.01; test $$? -eq 2
	./$(BIN) -q --bug no-full 1 1 4 0.01; test $$? -eq 2
	./$(BIN) -q --bug order 2 2 2 0.05; test $$? -eq 3
	@echo "== bad input (must be rejected, exit 1)"
	@for args in "" "1 2" "0 1 1" "abc 1 1" "1 0 1" "1 1 0" "1 1 101" "1 1 1 -1" "1 1 1 x"; do \
	  ./$(BIN) $$args >/dev/null 2>&1; rc=$$?; \
	  if [ $$rc -ne 1 ]; then echo "FAIL: '$$args' exit $$rc"; exit 1; fi; \
	  echo "ok   rejected: '$$args'"; done
	@echo "ALL TESTS PASSED"

clean:
	rm -f $(BIN) $(BIN)_tsan

.PHONY: run test tsan clean
