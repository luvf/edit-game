"""Pagination utilities for API views."""

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Standard page-number pagination with client-tunable page size."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100
