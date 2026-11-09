# find_package(NotARealDependency) appears only in this comment
add_executable(heat main.cpp kernels.f90)
find_package(ZLIB REQUIRED)
target_link_libraries(heat PRIVATE ZLIB::ZLIB BLAS::BLAS LAPACK::LAPACK)
