cmake_minimum_required(VERSION 3.18)
project(HeatSolver VERSION 2.1.0 LANGUAGES C CXX Fortran
        DESCRIPTION "A toy heat-equation solver")

option(HEAT_ENABLE_MPI "Build with MPI support" ON)
option(HEAT_USE_HDF5 "Write output with HDF5" OFF)
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
option(HEAT_WERROR "Treat warnings as errors" OFF)

include(CTest)

find_package(BLAS REQUIRED)
find_package(LAPACK REQUIRED)
find_package(OpenMP)
find_package(Boost 1.70 REQUIRED COMPONENTS filesystem program_options)

if(HEAT_ENABLE_MPI)
  find_package(MPI 3.0 REQUIRED COMPONENTS C CXX)
endif()

if(HEAT_USE_HDF5)
  find_package(HDF5 1.10 REQUIRED COMPONENTS C HL)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(FFTW REQUIRED IMPORTED_TARGET fftw3>=3.3)

add_subdirectory(src)
install(TARGETS heat DESTINATION bin)
