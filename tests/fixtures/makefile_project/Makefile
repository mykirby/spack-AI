CC = mpicc
FC = gfortran
PREFIX ?= /usr/local
CFLAGS = -O2 -fopenmp
LDLIBS = -lfftw3 -lm -llapack -lblas

ifeq ($(USE_HDF5),1)
  LDLIBS += -lhdf5
  CFLAGS += -DUSE_HDF5
endif

all: solver

solver: main.o
	$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)

install: solver
	mkdir -p $(PREFIX)/bin
	cp solver $(PREFIX)/bin

.PHONY: all install
