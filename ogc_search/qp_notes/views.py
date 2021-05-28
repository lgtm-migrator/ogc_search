from django.conf import settings
from django.shortcuts import render
from django.views.generic import View
import logging
import search_util
import os
from django.http import HttpRequest, HttpResponseRedirect, FileResponse
import hashlib
import time
from urlsafe import url_part_escape

logger = logging.getLogger('ogc_search')

def get_user_facet_parameters(request: HttpRequest):
    """
    Retrieve any selected search facets from the HTTP GET request
    :param request:
    :return: dictionary of strings of the accumulated search parameters
    """
    return {
        'solr_search_minister': request.GET.get('qp-search-minister', ''),
        'solr_search_minister_position': request.GET.get('qp-search-minister-positions', ''),
        'solr_search_minister_status': request.GET.get('qp-search-minister-status', ''),
        'solr_search_year': request.GET.get('qp-search-year', ''),
        'solr_search_month': request.GET.get('qp-search-month', ''),
        'solr_search_orgs': request.GET.get('qp-search-orgs', ''),
    }


class QPSearchView(View):
    # Question Period Search Page
    def __init__(self):
        super().__init__()

        # French search fields
        self.solr_fields_fr = ["id, reference_number_s, title_fr_txt,"
                               "minister_fr_txt, minister_position_fr_s, minister_position_fr_txt,"
                               "question_fr_txt, background_fr_txt, response_fr_txt, additional_information_fr_txt,"
                               "date_received_dt, month_i, year_i, owner_org_title_txt_fr, owner_org_fr_s, "]
        self.solr_query_fields_fr = ['reference_number_s^5', 'title_fr_txt^5', 'minister_position_fr_txt^4',
                                     'minister_fr_txt^4', 'question_fr_txt^4', 'owner_org_title_txt_fr^4',
                                     'background_fr_txt^3', 'response_fr_txt^3', 'additional_information_fr_txt^3', ]
        self.solr_facet_fields_fr = ['{!ex=tag_minister_position_fr_s}minister_position_fr_s',
                                     '{!ex=tag_month_i}month_i',
                                     '{!ex=tag_year_i}year_i',
                                     '{!ex=tag_minister_fr_s}minister_fr_s',
                                     '{!ex=tag_minister_status_fr_s}minister_status_fr_s',
                                     '{!ex=tag_owner_org_fr_s}owner_org_fr_s', ]
        self.solr_hl_fields_fr = ['question_fr_txt', 'title_fr_txt', 'owner_org_title_txt_fr', 'minster_fr_txt',
                                  'minister_position_fr_s', ]

        # English search fields
        self.solr_fields_en = ["id,reference_number_s, title_en_txt,"
                               "minister_en_txt, minister_position_en_s, minister_position_en_txt,"
                               "question_en_txt, background_en_txt, response_en_txt, additional_information_en_txt,"
                               "date_received_dt, month_i, year_i, owner_org_title_txt_en, owner_org_en_s",
                               ]
        self.solr_query_fields_en = ['reference_number_s^5', 'title_en_txt^5', 'minister_position_en_txt^4',
                                     'minister_en_txt^4', 'question_en_txt^4', 'owner_org_title_txt_en^4',
                                     'background_en_txt^3', 'response_en_txt^3', 'additional_information_en_txt^3', ]
        self.solr_facet_fields_en = ['{!ex=tag_minister_position_en_s}minister_position_en_s',
                                     '{!ex=tag_month_i}month_i',
                                     '{!ex=tag_year_i}year_i',
                                     '{!ex=tag_minister_en_s}minister_en_s',
                                     '{!ex=tag_minister_status_en_s}minister_status_en_s',
                                     '{!ex=tag_owner_org_en_s}owner_org_en_s', ]
        self.solr_hl_fields_en = ['question_en_txt', 'title_en_txt', 'owner_org_title_txt_en', 'minster_en_txt',
                                  'minister_position_en_s', 'minster_s', 'minister_position_en_txt', ]

        self.phrase_xtras_fr = {
            'hl': 'on',
            'hl.simple.pre': '<mark>',
            'hl.simple.post': '</mark>',
            'hl.method': 'unified',
            'hl.snippets': 10,
            'hl.fl': self.solr_hl_fields_fr,
            'hl.preserveMulti': 'true',
            'ps': 10,
            'mm': '3<70%',
            'bq': 'date_received_dt:[NOW/DAY-2YEAR TO NOW/DAY]',
        }
        self.phrase_xtras_en = {
            'hl': 'on',
            'hl.simple.pre': '<mark>',
            'hl.simple.post': '</mark>',
            'hl.method': 'unified',
            'hl.snippets': 10,
            'hl.fl': self.solr_hl_fields_en,
            'hl.preserveMulti': 'true',
            'ps': 10,
            'mm': '3<70%',
            'bq': 'date_received_dt:[NOW/DAY-2YEAR TO NOW/DAY]',
        }

    def get(self, request):

        context = dict(LANGUAGE_CODE=request.LANGUAGE_CODE, )
        context['query_string'] = request.META['QUERY_STRING']
        context['cdts_version'] = settings.CDTS_VERSION
        context['od_en_url'] = settings.OPEN_DATA_EN_URL_BASE
        context['od_fr_url'] = settings.OPEN_DATA_FR_URL_BASE
        context['ds_id'] = settings.QP_DATASET_ID
        context['ds_title_en'] = settings.QP_DATASET_TITLE_EN
        context['ds_title_fr'] = settings.QP_DATASET_TITLE_FR
        context['adobe_analytics_url'] = settings.ADOBE_ANALYTICS_URL
        # Allow for, but do not require, a custom alert message
        if hasattr(settings, 'OPEN_DATA_PORTAL_ALERT_BASE'):
            context['od_portal_alert_base'] = settings.OPEN_DATA_PORTAL_ALERT_BASE
        else:
            context['od_portal_alert_base'] = "/data/static/_site_messaging/header_od_ckan."

        items_per_page = int(settings.QP_ITEMS_PER_PAGE)
        start_row, page = search_util.calc_starting_row(request.GET.get('page', 1), items_per_page)

        if request.LANGUAGE_CODE == 'fr':
            context['info_msg'] = settings.QP_INFO_FR
        else:
            context['info_msg'] = settings.QP_INFO_EN

        # Get any search terms
        solr_search_terms = search_util.get_search_terms(request)
        context['search_text'] = str(request.GET.get('search_text', ''))

        # Retrieve search sort order
        if request.GET.get('sort') is None:
            # setup default sort
            solr_search_sort = 'date_received_dt desc'
        else:
            solr_search_sort = request.GET.get('sort', 'score desc')
            if request.LANGUAGE_CODE == 'fr':
                if solr_search_sort not in ['score desc', 'date_received_dt desc', 'title_fr_s asc']:
                    solr_search_sort = 'score desc'
            else:
                if solr_search_sort not in ['score desc', 'date_received_dt desc', 'title_en_s asc']:
                    solr_search_sort = 'score desc'
        context['sortby'] = solr_search_sort

        # Retrieve facets and transform facets results to python dict
        solr_search_year: str = request.GET.get('qp-search-year', '')
        solr_search_month: str = request.GET.get('qp-search-month', '')
        solr_search_minister: str = request.GET.get('qp-search-minister', '')
        solr_search_minister_status: str = request.GET.get('qp-search-minister-status', '')
        solr_search_minister_position: str = request.GET.get('qp-search-minister-positions', '')
        solr_search_orgs: str = request.GET.get('qp-search-orgs', '')

        context['year_selected'] = solr_search_year
        context['year_selected_list'] = solr_search_year.split('|')
        context['month_selected'] = solr_search_month
        context['month_selected_list'] = solr_search_month.split('|')
        context['minister_selected'] = solr_search_minister
        context['minister_selected_list'] = solr_search_minister.split('|')
        context['minister_position_selected'] = solr_search_minister_position
        context['minister_position_selected_list'] = solr_search_minister_position.split('|')
        context['minister_status_selected'] = solr_search_minister_status
        context['minister_status_selected_list'] = solr_search_minister_status.split('|')
        context["organizations_selected"] = solr_search_orgs
        context["organizations_selected_list"] = solr_search_orgs.split('|')

        if request.LANGUAGE_CODE == 'fr':
            facets_dict = dict(
                year_i=context['year_selected'],
                month_i=context['month_selected'],
                minister_fr_s=context['minister_selected'],
                minister_position_fr_s=context['minister_position_selected'],
                minister_status_fr_s=context['minister_status_selected'],
                owner_org_fr_s=context['organizations_selected'],
            )
        else:
            facets_dict = dict(
                year_i=context['year_selected'],
                month_i=context['month_selected'],
                minister_en_s=context['minister_selected'],
                minister_position_en_s=context['minister_position_selected'],
                minister_status_en_s=context['minister_status_selected'],
                owner_org_en_s=context['organizations_selected'],
            )

        # Generate search results
        if request.LANGUAGE_CODE == 'fr':
            search_results = search_util.solr_query(solr_search_terms,
                                                    settings.SOLR_QP,
                                                    self.solr_fields_fr,
                                                    self.solr_query_fields_fr,
                                                    self.solr_facet_fields_fr,
                                                    self.phrase_xtras_fr,
                                                    start_row=str(start_row), pagesize=str(items_per_page),
                                                    facets=facets_dict,
                                                    sort_order=solr_search_sort)

        else:
            search_results = search_util.solr_query(solr_search_terms,
                                                    settings.SOLR_QP,
                                                    self.solr_fields_en,
                                                    self.solr_query_fields_en,
                                                    self.solr_facet_fields_en,
                                                    self.phrase_xtras_en,
                                                    start_row=str(start_row), pagesize=str(items_per_page),
                                                    facets=facets_dict,
                                                    sort_order=solr_search_sort)

        context['results'] = search_results

        # Set pagination values for the page
        pagination = search_util.calc_pagination_range(context['results'], items_per_page, page)
        context['pagination'] = pagination
        context['previous_page'] = (1 if page == 1 else page - 1)
        last_page = (pagination[len(pagination) - 1] if len(pagination) > 0 else 1)
        last_page = (1 if last_page < 1 else last_page)
        context['last_page'] = last_page
        next_page = page + 1
        next_page = (last_page if next_page > last_page else next_page)
        context['next_page'] = next_page
        context['currentpage'] = page

        # Generate facet list for the search result
        if request.LANGUAGE_CODE == 'fr':
            context['minister_fr_s'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_fr_s'])
            context['minister_position_facets_fr'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_position_fr_s'])
            context['minister_status_facets_fr_s'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_status_fr_s'])
            context['org_facets_fr'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['owner_org_fr_s'])
        else:
            context['minister_en_s'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_en_s'])
            context['minister_position_facets_en'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_position_en_s'])
            context['minister_status_facets_en_s'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['minister_status_en_s'])
            context['org_facets_en'] = search_util.convert_facet_list_to_dict(
                search_results.facets['facet_fields']['owner_org_en_s'])

        context['month_i'] = search_util.convert_facet_list_to_dict(
            search_results.facets['facet_fields']['month_i'])
        context['year_i'] = search_util.convert_facet_list_to_dict(
            search_results.facets['facet_fields']['year_i'])

        # export url
        export_url = "/{0}/qp/export/?{1}".format(request.LANGUAGE_CODE, request.GET.urlencode())
        context['export_url'] = export_url
        return render(request, "qp_notes_search.html", context)


class QPCardView(QPSearchView):
    # Question Period Notes Details Page
    def __init__(self):
        super().__init__()
        self.phrase_xtras_en = {}
        self.phrase_xtras_fr = {}

    def get(self, request, slug=''):
        context = dict(LANGUAGE_CODE=request.LANGUAGE_CODE, )
        context["cdts_version"] = settings.CDTS_VERSION
        context["adobe_analytics_url"] = settings.ADOBE_ANALYTICS_URL
        context["slug"] = url_part_escape(slug)

        if 'HTTP_REFERER' in request.META \
                and request.META['HTTP_REFERER'] is not None \
                and request.META['HTTP_REFERER'].find('/qp/id/') == -1:
            context["back_url"] = request.META['HTTP_REFERER']
        else:
            context["back_url"] = '/' + request.LANGUAGE_CODE + '/qp/'

        solr_search_terms = 'id:"{0}"'.format(context["slug"])
        if request.LANGUAGE_CODE == 'fr':
            search_results = search_util.solr_query(solr_search_terms,
                                                    settings.SOLR_QP,
                                                    self.solr_fields_fr,
                                                    self.solr_query_fields_fr,
                                                    self.solr_facet_fields_fr,
                                                    self.phrase_xtras_fr)
        else:
            search_results = search_util.solr_query(solr_search_terms,
                                                    settings.SOLR_QP,
                                                    self.solr_fields_en,
                                                    self.solr_query_fields_en,
                                                    self.solr_facet_fields_en,
                                                    self.phrase_xtras_en)
        context['results'] = search_results
        if len(search_results.docs) > 0:
            context['reference_number_s'] = slug
            return render(request, "qp_notes.html", context)
        else:
            return render(request, 'no_record_found.html', context, status=404)


class QPExportView(View):
    """
    A view for downloading a simple CSV containing a subset of the fields from the Search View.
    """

    def __init__(self):
        super().__init__()

        # Fields to be returned by the Solr query, English and French Versions
        self.solr_fields_en = ("id,reference_number_s,title_en_s,"
                               "minister_en_s,minister_position_en_s,"
                               "question_en_s,background_en_s,response_en_s,additional_information_en_s,"
                               "date_received_dt,month_i,year_i,owner_org_en_s,")
        self.solr_fields_fr = ("id,reference_number_s,title_fr_s,"
                               "minister_fr_s,minister_position_fr_s,"
                               "question_fr_s,background_fr_s,response_fr_s,additional_information_fr_s,"
                               "date_received_dt,month_i,year_i,owner_org_fr_s,")

        # Fields to be searched in the Solr query. Fields can be weighted to indicate which are more relevant for
        # searching.
        self.solr_query_fields_en = ['reference_number_s^5', 'title_en_txt^5',
                                     'minister_en_txt^4', 'question_en_txt^4', 'owner_org_title_txt_en^4',
                                     'background_en_txt^3', 'response_en_txt^3', 'additional_information_en_txt^3', ]
        self.solr_query_fields_fr = ['reference_number_s^5', 'title_fr_txt^5',
                                     'minister_fr_txt^4', 'question_fr_txt^4', 'owner_org_title_txt_fr^4',
                                     'background_fr_txt^3', 'response_fr_txt^3', 'additional_information_fr_txt^3', ]

        # These fields are search facets
        self.solr_facet_fields_en = ['{!ex=tag_owner_org_en_s}owner_org_en_s',
                                     '{!ex=tag_minister_position_en_s}minister_position_en_s',
                                     '{!ex=tag_month_i}month_i',
                                     '{!ex=tag_year_i}year_i',
                                     '{!ex=tag_minister_en_s}minister_en_s',
                                     '{!ex=tag_minister_status_en_s}minister_status_en_s', ]
        self.solr_facet_fields_fr = ['{!ex=tag_owner_org_fr_s}owner_org_fr_s',
                                     '{!ex=tag_minister_position_fr_s}minister_position_fr_s',
                                     '{!ex=tag_month_i}month_i',
                                     '{!ex=tag_year_i}year_i',
                                     '{!ex=tag_minister_fr_s}minister_fr_s',
                                     '{!ex=tag_minister_status_fr_s}minister_status_fr_s', ]
        self.phrase_xtras = {
            'mm': '3<70%',
        }
        self.cache_dir = settings.EXPORT_FILE_CACHE_DIR
        if not os.path.exists(self.cache_dir):
            os.mkdir(self.cache_dir)

    def get(self, request: HttpRequest):

        # Check to see if a recent cached results exists and return that instead if it exists
        hashed_query = hashlib.sha1(request.GET.urlencode().encode('utf8')).hexdigest()
        cached_filename = os.path.join(self.cache_dir, "{}.csv".format(hashed_query))
        if os.path.exists(cached_filename):
            if time.time() - os.path.getmtime(cached_filename) > 600:
                os.remove(cached_filename)
            else:
                if settings.EXPORT_FILE_CACHE_URL == "":
                    return FileResponse(open(cached_filename, 'rb'), as_attachment=True)
                else:
                    return HttpResponseRedirect(settings.EXPORT_FILE_CACHE_URL + "{}.csv".format(hashed_query))

        # Retrieve any selected search facets
        params = get_user_facet_parameters(request)

        solr_search_terms = search_util.get_search_terms(request)
        solr_fields = self.solr_fields_en
        solr_search_facets = self.solr_facet_fields_en
        solr_query_fields = self.solr_query_fields_en

        if request.LANGUAGE_CODE == 'fr':
            facets_dict = dict(minister_fr_txt=params['solr_search_minister'],
                               minister_position_fr_s=params['solr_search_minister_position'],
                               minister_status_fr_s=params['solr_search_minister_status'],
                               year_i=params['solr_search_year'],
                               month_i=params['solr_search_month'],
                               owner_org_fr_s=params['solr_search_orgs'],
                               )

            solr_fields = self.solr_fields_fr
            solr_search_facets = self.solr_facet_fields_fr
            solr_query_fields = self.solr_query_fields_fr
        else:
            facets_dict = dict(minister_en_txt=params['solr_search_minister'],
                               minister_position_en_s=params['solr_search_minister_position'],
                               minister_status_en_s=params['solr_search_minister_status'],
                               year_i=params['solr_search_year'],
                               month_i=params['solr_search_month'],
                               owner_org_en_s=params['solr_search_orgs'],
                               )

        search_results = search_util.solr_query_for_export(solr_search_terms,
                                                           settings.SOLR_QP,
                                                           solr_fields,
                                                           solr_query_fields,
                                                           solr_search_facets,
                                                           "id asc",
                                                           facets_dict,
                                                           self.phrase_xtras)

        if search_util.cache_search_results_file(cached_filename=cached_filename, sr=search_results):
            if settings.EXPORT_FILE_CACHE_URL == "":
                return FileResponse(open(cached_filename, 'rb'), as_attachment=True)
            else:
                return HttpResponseRedirect(settings.EXPORT_FILE_CACHE_URL + "{}.csv".format(hashed_query))
