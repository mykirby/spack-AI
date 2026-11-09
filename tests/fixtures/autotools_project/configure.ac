AC_PREREQ([2.69])
AC_INIT([libwidget], [0.9.1], [bugs@example.org], [libwidget], [https://example.org/libwidget])
AM_INIT_AUTOMAKE([foreign])
LT_INIT
AC_PROG_CC
AC_PROG_CXX
dnl optional features
AC_ARG_ENABLE([shared-memory],
  AS_HELP_STRING([--enable-shared-memory], [use POSIX shared memory]))
AC_ARG_WITH([zlib], AS_HELP_STRING([--with-zlib], [compress output with zlib]))
AC_CHECK_LIB([m], [cos])
AC_CHECK_LIB([z], [deflate])
PKG_CHECK_MODULES([GLIB], [glib-2.0 >= 2.56])
AX_MPI
AC_CONFIG_FILES([Makefile])
AC_OUTPUT
