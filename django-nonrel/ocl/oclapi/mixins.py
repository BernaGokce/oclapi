from django.core.urlresolvers import resolve
from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response

__author__ = 'misternando'

HEAD = 'HEAD'

class PathWalkerMixin():
    """
    A Mixin with methods that help resolve a resource path to a resource object
    """
    path_info = None

    def get_parent_in_path(self, path_info, levels=1):
        last_index = len(path_info) - 1
        last_slash = path_info.rindex('/')
        if last_slash == last_index:
            last_slash = path_info.rindex('/', 0, last_index)
        path_info = path_info[0:last_slash+1]
        if levels > 1:
            i = 1
            while i < levels:
                last_index = len(path_info) - 1
                last_slash = path_info.rindex('/', 0, last_index)
                path_info = path_info[0:last_slash+1]
                i += 1
        return path_info

    def get_object_for_path(self, path_info, request):
        callback, callback_args, callback_kwargs = resolve(path_info)
        view = callback.cls(request=request, kwargs=callback_kwargs)
        view.initialize(request, path_info, **callback_kwargs)
        return view.get_object()


class ListWithHeadersMixin(ListModelMixin):
    verbose_param = 'verbose'
    facets = None
    default_filters = {'is_active': True}
    object_list = None

    def is_verbose(self, request):
        return request.QUERY_PARAMS.get(self.verbose_param, False)

    def list(self, request, *args, **kwargs):
        self.object_list = self.object_list or self.filter_queryset(self.get_queryset())

        # Skip pagination if compressed results are requested
        meta = request._request.META
        include_facets = meta.get('HTTP_INCLUDEFACETS', False)
        facets = None
        if include_facets and hasattr(self.object_list, 'facets'):
            facets = self.object_list.facets

        compress = meta.get('HTTP_COMPRESS', False)
        return_all = self.get_paginate_by() == 0
        skip_pagination = compress or return_all

        # Switch between paginated or standard style responses
        if not skip_pagination:
            page = self.paginate_queryset(self.object_list)
            if page is not None:
                serializer = self.get_pagination_serializer(page)
                results = serializer.data
                results = self.prepend_head(results)
                if facets:
                    return Response({'results': results, 'facets': facets}, headers=serializer.headers)
                else:
                    return Response(results, headers=serializer.headers)

        serializer = self.get_serializer(self.object_list, many=True)
        results = serializer.data
        results = self.prepend_head(results)
        if facets:
            return Response({'results': results, 'facets': facets})
        else:
            return Response(results)

    @staticmethod
    def prepend_head(results):
        if len(results) > 0 and 'id' in results[0]:
            head_el = [el for el in results if el['id'] == HEAD]
            if head_el:
                results = head_el + [el for el in results if el['id'] != HEAD]

        return results



