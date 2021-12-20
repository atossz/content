import functools
import uuid
from flask import Flask, request, make_response, jsonify
from urllib.parse import ParseResult, urlparse
from secrets import compare_digest
from dateutil.parser import parse
from requests.utils import requote_uri

import demistomock as demisto
from CommonServerPython import *

''' GLOBAL VARIABLES '''
HTTP_200_OK = 200
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_404_NOT_FOUND = 404
HTTP_406_NOT_ACCEPABLE = 406
INTEGRATION_NAME: str = 'TAXII Server'
API_ROOT = 'threatintel'
APP: Flask = Flask('demisto-taxii2Z')
NAMESPACE_URI = 'https://www.paloaltonetworks.com/cortex'
MEDIA_TYPE_TAXII_ANY = 'application/taxii+json'
MEDIA_TYPE_STIX_ANY = 'application/stix+json'
MEDIA_TYPE_TAXII_V21 = 'application/taxii+json;version=2.1'
MEDIA_TYPE_STIX_V21 = 'application/stix+json;version=2.1'
MEDIA_TYPE_TAXII_V20 = 'application/vnd.oasis.taxii+json; version=2.0'
MEDIA_TYPE_STIX_V20 = 'application/vnd.oasis.stix+json; version=2.0'
ACCEPT_TYPE_ALL = '*/*'
TAXII_VER_2_0 = '2.0'
TAXII_VER_2_1 = '2.1'
PAWN_UUID = uuid.uuid5(uuid.NAMESPACE_URL, 'https://www.paloaltonetworks.com')
SCO_DET_ID_NAMESPACE = uuid.UUID('00abedb4-aa42-466c-9c01-fed23315a9b7')
STIX_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'

XSOAR_TYPES_TO_STIX_SCO = {
    FeedIndicatorType.CIDR: 'ipv4-addr',
    FeedIndicatorType.DomainGlob: 'domain-name',
    FeedIndicatorType.IPv6: 'ipv6-addr',
    FeedIndicatorType.IPv6CIDR: 'ipv6-addr',
    FeedIndicatorType.Account: 'user-account',
    FeedIndicatorType.Domain: 'domain-name',
    FeedIndicatorType.Email: 'email-addr',
    FeedIndicatorType.IP: 'ipv4-addr',
    FeedIndicatorType.Registry: 'windows-registry-key',
    FeedIndicatorType.File: 'file',
    FeedIndicatorType.URL: 'url',
}

XSOAR_TYPES_TO_STIX_SDO = {
    ThreatIntel.ObjectsNames.ATTACK_PATTERN: 'attack-pattern',
    ThreatIntel.ObjectsNames.CAMPAIGN: 'campaign',
    ThreatIntel.ObjectsNames.COURSE_OF_ACTION: 'course-of-action',
    ThreatIntel.ObjectsNames.INFRASTRUCTURE: 'infrastructure',
    ThreatIntel.ObjectsNames.INTRUSION_SET: 'instruction-set',
    ThreatIntel.ObjectsNames.REPORT: 'report',
    ThreatIntel.ObjectsNames.THREAT_ACTOR: 'threat-actor',
    ThreatIntel.ObjectsNames.TOOL: 'tool',
    ThreatIntel.ObjectsNames.MALWARE: 'malware',
    FeedIndicatorType.CVE: 'vulnerability',
}

STIX2_TYPES_TO_XSOAR = {
    'campaign': ThreatIntel.ObjectsNames.CAMPAIGN,
    'attack-pattern': ThreatIntel.ObjectsNames.ATTACK_PATTERN,
    'report': ThreatIntel.ObjectsNames.REPORT,
    'malware': ThreatIntel.ObjectsNames.MALWARE,
    'course-of-action': ThreatIntel.ObjectsNames.COURSE_OF_ACTION,
    'intrusion-set': ThreatIntel.ObjectsNames.INTRUSION_SET,
    'tool': ThreatIntel.ObjectsNames.TOOL,
    'threat-actor': ThreatIntel.ObjectsNames.THREAT_ACTOR,
    'infrastructure': ThreatIntel.ObjectsNames.INFRASTRUCTURE,
    'vulnerability': FeedIndicatorType.CVE,
    "ipv4-addr": FeedIndicatorType.IP,
    "ipv6-addr": FeedIndicatorType.IPv6,
    "domain-name": [FeedIndicatorType.DomainGlob, FeedIndicatorType.Domain],
    'user-account': FeedIndicatorType.Account,
    'email-addr': FeedIndicatorType.Email,
    "url": FeedIndicatorType.URL,
    "file": FeedIndicatorType.File,
    'windows-registry-key': FeedIndicatorType.Registry,
}

NGINX_TAXII2SERVER_CONF = '''
server {

    listen $port default_server $ssl;

    $sslcerts

    proxy_cache_key $scheme$proxy_host$request_uri$extra_cache_key$http_range$http_content_range;
    proxy_set_header Range $http_range;

    # Static test file
    location = /nginx-test {
        alias /var/lib/nginx/html/index.html;
        default_type text/html;
    }

    # Proxy everything to python
    location / {
        proxy_pass http://localhost:$serverport/;
        add_header X-Proxy-Cache $upstream_cache_status;
        # allow bypassing the cache with an arg of nocache=1 ie http://server:7000/?nocache=1
        proxy_cache_bypass $arg_nocache;
    }
}

'''

''' TAXII2 Server '''


class TAXII2Server:
    def __init__(self, url_scheme: str, host: str, port: int, collections: dict, certificate: str, private_key: str,
                 http_server: bool, credentials: dict, version: str, service_address: Optional[str] = None):
        """
        Class for a TAXII2 Server configuration.
        Args:
            url_scheme: The URL scheme (http / https)
            host: The server address.
            port: The server port.
            collections: The JSON string of collections of indicator queries.
            certificate: The server certificate for SSL.
            private_key: The private key for SSL.
            http_server: Whether to use HTTP server (not SSL).
            credentials: The user credentials.
            version: API version.
        """
        self._url_scheme = url_scheme
        self._host = host
        self._port = port
        self._certificate = certificate
        self._private_key = private_key
        self._http_server = http_server
        self._service_address = service_address
        self._auth = None
        if credentials and (identifier := credentials.get('identifier')) and (password := credentials.get('password')):
            self._auth = (identifier, password)
        self.version = version
        if not (version == TAXII_VER_2_0 or version == TAXII_VER_2_1):
            raise Exception(f'Wrong TAXII 2 Server version: {version}. '
                            f'Possible values: {TAXII_VER_2_0}, {TAXII_VER_2_1}.')
        self._collections_resource: list = []
        self.collections_by_id: dict = dict()
        self.namespace_uuid = uuid.uuid5(PAWN_UUID, demisto.getLicenseID())
        self.create_collections(collections)

    @property
    def taxii_collections_media_type(self):
        media_type = MEDIA_TYPE_STIX_ANY
        if self.version == TAXII_VER_2_0:
            media_type = MEDIA_TYPE_STIX_V20
        elif self.version == TAXII_VER_2_1:
            media_type = MEDIA_TYPE_STIX_V21
        return media_type

    @property
    def taxii_content_type(self):
        content_type = MEDIA_TYPE_TAXII_ANY
        if self.version == TAXII_VER_2_0:
            content_type = MEDIA_TYPE_TAXII_V20
        elif self.version == TAXII_VER_2_1:
            content_type = MEDIA_TYPE_TAXII_V21
        return content_type

    @property
    def discovery_route(self):
        discovery_route = '/taxii/'
        if self.version == TAXII_VER_2_1:
            discovery_route = '/taxii2/'
        return discovery_route

    @property
    def api_version(self):
        api_root_version = 'taxii-2.0'
        if self.version == TAXII_VER_2_1:
            api_root_version = MEDIA_TYPE_TAXII_V21
        return api_root_version

    @property
    def auth(self):
        return self._auth

    def create_collections(self, collections):
        """
        Creates collection resources from collection params.
        """
        collections_resource = []
        collections_by_id = dict()
        for name, query_dict in collections.items():
            description = ''
            if isinstance(query_dict, dict):
                query = query_dict.get('query')
                description = query_dict.get('description', '')
            else:
                query = query_dict
            collection_uuid = str(uuid.uuid5(self.namespace_uuid, 'Collection_' + name))
            collection = {
                'id': collection_uuid,
                'title': name,
                'description': description,
                'can_read': True,
                'can_write': False,
                'media_types': [self.taxii_collections_media_type],
                'query': query
            }
            collections_resource.append(collection)
            collections_by_id[collection_uuid] = collection

        self._collections_resource = collections_resource
        self.collections_by_id = collections_by_id

    def get_discovery_service(self):
        """
        Handle discovery request.

        Returns:
            The discovery response.
        """
        request_headers = request.headers
        if self._service_address:
            service_address = self._service_address
        elif request_headers and '/instance/execute' in request_headers.get('X-Request-URI', ''):
            # if the server rerouting is used, then the X-Request-URI header is added to the request by the server
            # and we should use the /instance/execute endpoint in the address
            self._url_scheme = 'https'
            calling_context = get_calling_context()
            instance_name = calling_context.get('IntegrationInstance', '')
            endpoint = requote_uri(os.path.join('/instance', 'execute', instance_name))
            service_address = f'{self._url_scheme}://{self._host}{endpoint}'
        else:
            endpoint = f':{self._port}'
            service_address = f'{self._url_scheme}://{self._host}{endpoint}'

        default = urljoin(service_address, API_ROOT)
        default = urljoin(default, '/')
        return {
            'title': 'XSOAR TAXII2 Server',
            'description': 'This integration provides TAXII Services for system indicators (Outbound feed).',
            'default': default,
            'api_roots': [default]
        }

    def get_api_root(self):
        """
        Handle API Root request.

        Returns:
            The API ROOT response.
        """
        return {
            'title': 'XSOAR TAXII2 Server ThreatIntel',
            'description': 'This API Root provides TAXII Services for system indicators.',
            'versions': [self.api_version],
            'max_content_length': 9765625 if self.version == TAXII_VER_2_0 else 104857600
        }

    def get_collections(self):
        """
        Handle Collections request.

        Returns:
            The Collections response.
        """
        return self._collections_resource

    def get_collection_by_id(self, collection_id):
        """
        Handle Collection ID request.

        Returns:
            The Collection with given ID response.
        """
        found_collection = self.collections_by_id.get(collection_id)
        return found_collection

    def get_manifest(self, collection_id: str, added_after, limit: int, offset: int,
                     types: list):
        """
        Handle Manifest request.

        Returns:
            The objects from given collection ID.
        """
        found_collection = self.collections_by_id.get(collection_id, {})
        query = found_collection.get('query')
        new_limit = offset + limit + 1  # helps to verify that there is more indicators
        new_query = create_query(query, types)
        iocs, _ = find_indicators(query=new_query, added_after=added_after, limit=new_limit, is_manifest=True)

        first_added = None
        last_added = None
        objects = iocs[offset:offset + limit]

        if objects:
            first_added = parse(objects[0].get('date_added')).strftime(STIX_DATE_FORMAT)
            last_added = parse(objects[-1].get('date_added')).strftime(STIX_DATE_FORMAT)

        response = {
            'objects': objects,
        }

        if self.version == TAXII_VER_2_1:
            if len(iocs) > offset + limit:
                response['more'] = True
                response['next'] = str(limit + offset)

        return response, first_added, last_added

    def get_objects(self, collection_id: str, added_after, limit: int, offset: int, types: list):
        """
        Handle Objects request.

        Returns:
            The objects from given collection ID.
        """

        found_collection = self.collections_by_id.get(collection_id, {})
        query = found_collection.get('query')
        new_limit = offset + limit + 1  # helps to verify that there is more indicators
        new_query = create_query(query, types)
        iocs, extensions = find_indicators(query=new_query, added_after=added_after, limit=new_limit)

        first_added = None
        last_added = None

        limited_iocs = iocs[offset:offset + limit]
        limited_extensions = extensions[offset:offset + limit]

        objects = [val for pair in zip(limited_iocs, limited_extensions) for val in pair]

        if limited_iocs:
            first_added = parse(limited_extensions[0].get('created')).strftime(STIX_DATE_FORMAT)
            last_added = parse(limited_extensions[-1].get('created')).strftime(STIX_DATE_FORMAT)

        response = {}
        if self.version == TAXII_VER_2_0:
            response = {
                'type': 'bundle',
                'objects': objects,
                'id': uuid.uuid4()
            }
        elif self.version == TAXII_VER_2_1:
            response = {
                'objects': objects,
            }
            if len(iocs) > offset + limit:
                response['more'] = True
                response['next'] = str(limit + offset)

        return response, first_added, last_added


SERVER: TAXII2Server = None  # type: ignore

''' HELPER FUNCTIONS '''


def taxii_validate_request_headers(f):
    @functools.wraps(f)
    def validate_request_headers(*args, **kwargs):
        """
        function for HTTP requests to validate authentication and Accept headers.
        """
        accept_headers = [MEDIA_TYPE_TAXII_ANY, MEDIA_TYPE_TAXII_V20, MEDIA_TYPE_TAXII_V21,
                          MEDIA_TYPE_STIX_V20, ACCEPT_TYPE_ALL]
        credentials = request.authorization

        if SERVER.auth:
            if credentials:
                try:
                    auth_success = (compare_digest(credentials.username, SERVER.auth[0])  # type: ignore
                                    and compare_digest(credentials.password, SERVER.auth[1]))  # type: ignore
                except TypeError:
                    auth_success = False
            else:
                auth_success = False
            if not auth_success:
                handle_long_running_error('Authorization failed')
                return handle_response(HTTP_401_UNAUTHORIZED, {'title': 'Authorization failed'})

        request_headers = request.headers
        if (accept_header := request_headers.get('Accept')) not in accept_headers:
            handle_long_running_error('Invalid TAXII Headers')
            return handle_response(HTTP_406_NOT_ACCEPABLE,
                                   {'title': 'Invalid TAXII Headers',
                                    'description': f'Invalid Accept header: {accept_header}, '
                                                   f'please use one ot the following Accept headers: '
                                                   f'{accept_headers}'})
        return f(*args, **kwargs)

    return validate_request_headers


def taxii_validate_url_param(f):
    @functools.wraps(f)
    def validate_url_param(*args, **kwargs):
        """
        function for HTTP/HTTPS requests to validate api_root and collection_id.
        """
        api_root = kwargs.get('api_root')
        collection_id = kwargs.get('collection_id')
        if api_root and not api_root == API_ROOT:
            handle_long_running_error('Unknown API Root')
            return handle_response(HTTP_404_NOT_FOUND,
                                   {'title': 'Unknown API Root',
                                    'description': f"Unknown API Root {api_root}. Check possible API Roots using "
                                                   f"'{SERVER.discovery_route}'"})

        if collection_id:
            if not SERVER.collections_by_id.get(collection_id):
                handle_long_running_error('Unknown Collection')
                return handle_response(HTTP_404_NOT_FOUND,
                                       {'title': 'Unknown Collection',
                                        'description': f'No collection with id "{collection_id}". '
                                                       f'Use "/{api_root}/collections/" to get '
                                                       f'all existing collections.'})

        return f(*args, **kwargs)

    return validate_url_param


def handle_long_running_error(error: str):
    """
    Handle errors in the long running process.
    Args:
        error: The error message.
    """
    demisto.error(error)
    demisto.updateModuleHealth(error)


def handle_response(status_code, content, date_added_first=None, date_added_last=None,
                    content_type=None):
    """
    Create an HTTP taxii response from a taxii message.
    Args:
        status_code: status code to return
        content_type: response content type to return
        date_added_last: last added item creation time
        date_added_first: first added item creation time
        content: response data

    Returns:
        A taxii HTTP response.
    """
    if not content_type:
        content_type = SERVER.taxii_content_type
    headers = {
        'Content-Type': content_type,
    }
    if status_code == HTTP_401_UNAUTHORIZED:
        headers['WWW-Authenticate'] = 'Basic realm="Authentication Required"'
    if date_added_first:
        headers['X-TAXII-Date-Added-First'] = date_added_first
    if date_added_last:
        headers['X-TAXII-Date-Added-Last'] = date_added_last

    return make_response(jsonify(content), status_code, headers)


def create_query(query, types):
    """
    Args:
        query: collections query
        types: indicator types to filter by

    Returns:
        New query with types params
    """
    if types:
        try:
            xsoar_types = [STIX2_TYPES_TO_XSOAR[t] for t in types if t != 'domain-name']
            if 'domain-name' in types:
                xsoar_types.extend(STIX2_TYPES_TO_XSOAR['domain-name'])
        except KeyError as e:
            raise Exception(f'Unsupported object type: {e}.')
        new_query = query + ' '
        new_query += ' or '.join(['type:' + x for x in xsoar_types])  # type: ignore
        demisto.debug(f'new query: {new_query}')
        return new_query
    else:
        return query


def find_indicators(query: str, added_after, limit: int, is_manifest: bool = False):
    """
    Args:
        query: search indicators query
        added_after: search indicators after this date
        limit: response items limit
        is_manifest: whether this call is for manifest or indicators

    Returns: Created indicators and its extensions.
    """
    iocs = []
    extensions = []
    indicator_searcher = IndicatorsSearcher(
        query=query,
        limit=limit,
        from_date=added_after
    )
    for ioc in indicator_searcher:
        found_indicators = ioc.get('iocs') or []
        for xsoar_indicator in found_indicators:
            xsoar_type = xsoar_indicator.get('indicator_type')
            if is_manifest:
                manifest_entry = create_manifest_entry(xsoar_indicator, xsoar_type)
                if manifest_entry:
                    iocs.append(manifest_entry)
            else:
                stix_ioc, extension_definition = create_stix_object(xsoar_indicator, xsoar_type)
                if stix_ioc and extension_definition:
                    iocs.append(stix_ioc)
                    extensions.append(extension_definition)

    return iocs, extensions


def create_sco_stix_uuid(xsoar_indicator, stix_type):
    """
    Create uuid for sco objects.
    """
    value = xsoar_indicator.get('value')
    if stix_type == 'user-account':
        account_type = xsoar_indicator.get('CustomFields', {}).get('accounttype')
        user_id = xsoar_indicator.get('CustomFields', {}).get('userid')
        unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE,
                               '{"account_login":"' + value + '","account_type":"' + account_type + '","user_id":"'
                               + user_id + '"}')
    elif stix_type == 'windows-registry-key':
        unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"key":"' + value + '"}')
    elif stix_type == 'file':
        custom_fields = xsoar_indicator.get('CustomFields', {})
        if md5 := custom_fields.get('md5'):
            unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"hashes":{"MD5":"' + md5 + '"}')
        elif sha1 := custom_fields.get('sha1'):
            unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"hashes":{"SHA-1":"' + sha1 + '"}')
        elif sha256 := custom_fields.get('sha256'):
            unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"hashes":{"SHA-256":"' + sha256 + '"}')
        elif sha512 := custom_fields.get('sha512'):
            unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"hashes":{"SHA-512":"' + sha512 + '"}')
        else:
            unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"value":"' + value + '"}')
    else:
        unique_id = uuid.uuid5(SCO_DET_ID_NAMESPACE, '{"value":"' + value + '"}')

    stix_id = f'{stix_type}--{unique_id}'
    return stix_id


def create_sdo_stix_uuid(xsoar_indicator, stix_type):
    """
    Create uuid for sdo objects.
    """
    value = xsoar_indicator.get('value')
    if stix_type == 'attack-pattern':
        if mitre_id := xsoar_indicator.get('CustomFields', {}).get('mitreid'):
            unique_id = uuid.uuid5(SERVER.namespace_uuid, f'{stix_type}:{mitre_id}')
        else:
            unique_id = uuid.uuid5(SERVER.namespace_uuid, f'{stix_type}:{value}')
    else:
        unique_id = uuid.uuid5(SERVER.namespace_uuid, f'{stix_type}:{value}')

    stix_id = f'{stix_type}--{unique_id}'
    return stix_id


def create_manifest_entry(xsoar_indicator, xsoar_type):
    """

    Args:
        xsoar_indicator: to create manifest entry from
        xsoar_type: type of indicator in xsoar system

    Returns:
        manifest entry for given indicator.
    """
    if stix_type := XSOAR_TYPES_TO_STIX_SCO.get(xsoar_type):
        stix_id = create_sco_stix_uuid(xsoar_indicator, stix_type)
    elif stix_type := XSOAR_TYPES_TO_STIX_SDO.get(xsoar_type):
        stix_id = create_sdo_stix_uuid(xsoar_indicator, stix_type)
    else:
        demisto.debug(f'No such indicator type: {xsoar_type} in stix format.')
        return {}
    entry = {
        'id': stix_id,
        'date_added': parse(xsoar_indicator.get('timestamp')).strftime(STIX_DATE_FORMAT),
    }
    if SERVER.version == TAXII_VER_2_1:
        entry['version'] = xsoar_indicator.get('version')
    return entry


def create_stix_object(xsoar_indicator, xsoar_type):
    """

    Args:
        xsoar_indicator: to create stix object entry from
        xsoar_type: type of indicator in xsoar system

    Returns:
        Stix object entry for given indicator, and extension. Format described here:
        (https://docs.google.com/document/d/12alMmfpJn5sQO18h_qzbRa_Yxvj_0P1R9bOEhtk_u8A/edit)
    """
    if stix_type := XSOAR_TYPES_TO_STIX_SCO.get(xsoar_type):
        stix_id = create_sco_stix_uuid(xsoar_indicator, stix_type)
        object_type = stix_type
    elif stix_type := XSOAR_TYPES_TO_STIX_SDO.get(xsoar_type):
        stix_id = create_sdo_stix_uuid(xsoar_indicator, stix_type)
        object_type = stix_type
    else:
        demisto.debug(f'No such indicator type: {xsoar_type} in stix format.')
        return {}

    xsoar_indicator['extension_type'] = 'property_extension'
    extention_id = f'extension-definition--{uuid.uuid4()}'
    extension_definition = {
        'id': extention_id,
        'type': 'extension-definition',
        'spec_version': SERVER.version,
        'name': f'XSOAR TIM {xsoar_type}',
        'description': 'This schema adds TIM data to the object',
        'created': xsoar_indicator.get('timestamp'),
        'modified': xsoar_indicator.get('modified'),
        'created_by_ref': f'identity--{str(PAWN_UUID)}',
        'schema':
            'https://github.com/demisto/content/tree/master/Packs/TAXIIServer/doc_files/XSOAR_indicator_schema.json',
        'version': '1.0',
        'extension_types': ['property-extension']
    }
    sco_object = {
        'id': stix_id,
        'value': xsoar_indicator.get('value'),
        'type': object_type,
        'spec_version': SERVER.version,
        'extensions': {
            extention_id: xsoar_indicator,
        },
    }
    return sco_object, extension_definition


def parse_content_range(content_range):
    """

    Args:
        content_range: the content-range or range header to parse.

    Returns:
        Offset and limit arguments for the command.
    """
    range_type, range_count = content_range.split(' ', 1)

    if range_type != 'items':
        raise Exception(f'Bad Content-Range header: {content_range}.')

    range_count = range_count.split('/')
    range_begin, range_end = range_count[0].split('-', 1)

    offset = int(range_begin)
    limit = int(range_end) - offset

    return offset, limit


def get_collections(params: dict = demisto.params()) -> dict:
    """
    Gets the indicator query collections from the integration parameters.
    """
    collections_json: str = params.get('collections', '')

    try:
        collections = json.loads(collections_json)
    except Exception:
        raise ValueError('The collections string must be a valid JSON object.')

    return collections


def get_calling_context():
    return demisto.callingContext.get('context', {})  # type: ignore[attr-defined]


''' ROUTE FUNCTIONS '''


@APP.route('/taxii/', methods=['GET'])  # TAXII v2.0
@APP.route('/taxii2/', methods=['GET'])  # TAXII v2.1
@taxii_validate_request_headers
def taxii2_server_discovery():
    """
    Defines TAXII API - Server Information:
    Server Discovery section (4.1) `here  for v2.1
    <https://docs.oasis-open.org/cti/taxii/v2.1/cs01/taxii-v2.1-cs01.html#_Toc31107526>`__
    and `here for v2.0 <http://docs.oasis-open.org/cti/taxii/v2.0/cs01/taxii-v2.0-cs01.html#_Toc496542727>`__
    Returns:
        discovery: A Discovery Resource upon successful requests.
    """
    try:
        discovery_response = SERVER.get_discovery_service()
    except Exception as e:
        error = f'Could not perform the discovery request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Discovery Request Error',
                                                      'description': error})

    return handle_response(HTTP_200_OK, discovery_response)


@APP.route('/<api_root>/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_api_root(api_root: str):
    """
     Defines TAXII API - Server Information:
     Get API Root Information section (4.2) `here
     <https://docs.oasis-open.org/cti/taxii/v2.1/cs01/taxii-v2.1-cs01.html#_Toc31107528>`__
     Args:
         api_root (str): the base URL of the API Root
     Returns:
         api-root: An API Root Resource upon successful requests.
     """
    try:
        api_root_response = SERVER.get_api_root()
    except Exception as e:
        error = f'Could not perform the API Root request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'API Root Request Error',
                                                      'description': error})

    return handle_response(HTTP_200_OK, api_root_response)


@APP.route('/<api_root>/status/<status_id>/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_status(api_root, status_id):  # noqa: F841
    """Status API call used to check status for adding object to the system.
    Our collections are read only. No option to add objects.
    Then All status requests ending with error.

    Returns: Error response.
    """
    return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Get Status not allowed.',
                                                  'description': 'All collections are read-only. '
                                                                 'Adding objects is not allowed.'})


@APP.route('/<api_root>/collections/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_collections(api_root: str):
    """
    Defines TAXII API - Collections:
    Get Collection section (5.1) `here for v.2
    <https://docs.oasis-open.org/cti/taxii/v2.1/csprd01/taxii-v2.1-csprd01.html#_Toc532988049>`__
    Args:
        api_root (str): the base URL of the API Root
    Returns:
        collections: A Collections Resource upon successful requests. Additional information
        `here <https://docs.oasis-open.org/cti/taxii/v2.1/csprd01/taxii-v2.1-csprd01.html#_Toc532988050>`__.
    """
    try:
        collections_response = SERVER.get_collections()
    except Exception as e:
        error = f'Could not perform the collections request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Collections Request Error',
                                                      'description': error})
    return handle_response(HTTP_200_OK, collections_response)


@APP.route('/<api_root>/collections/<collection_id>/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_collection_by_id(api_root: str, collection_id: str):
    """
    Defines TAXII API - Collections:
    Get Collection section (5.2) `here for v.2.0
    <http://docs.oasis-open.org/cti/taxii/v2.0/cs01/taxii-v2.0-cs01.html#_Toc496542736>`__
    and `here for v.2.1 <https://docs.oasis-open.org/cti/taxii/v2.1/csprd01/taxii-v2.1-csprd01.html#_Toc532988051>`__
    Args:
        collection_id: the is of the collection, can be obtained using `collection` request.
        api_root (str): the base URL of the API Root
    Returns:
        collections: A Collection Resource with given id upon successful requests.
    """
    try:
        collection_response = SERVER.get_collection_by_id(collection_id)
    except Exception as e:
        error = f'Could not perform the collection request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Collection Request Error',
                                                      'description': error})
    return handle_response(HTTP_200_OK, collection_response)


@APP.route('/<api_root>/collections/<collection_id>/manifest/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_manifest(api_root: str, collection_id: str):
    """
    Defines TAXII API - Manifest Objects:
    Get Manifest section (5.3) `here
    <https://docs.oasis-open.org/cti/taxii/v2.1/os/taxii-v2.1-os.html#_Toc31107537>`__
    Args:
        collection_id: collection id to query it objects
        api_root (str): the base URL of the API Root
    Returns:
        manifest: A Manifest Resource upon successful requests. Additional information
        `here <https://docs.oasis-open.org/cti/taxii/v2.1/os/taxii-v2.1-os.html#_Toc31107538>`__.
    """
    try:
        added_after = request.args.get('added_after')
        types = argToList(request.args.get('match[type]'))
        limit = 100
        offset = 0

        if request.args.get('match[id]') or request.args.get('match[version]'):
            raise Exception('Filtering by id or version is not supported.')

        try:
            if added_after:
                datetime.strptime(added_after, STIX_DATE_FORMAT)
        except ValueError as e:
            raise Exception(f'Added after time format should be YYYY-MM-DDTHH:mm:ss.[s+]Z. {e}')

        if SERVER.version == TAXII_VER_2_0:
            if content_range := request.headers.get('Content-Range'):
                offset, limit = parse_content_range(content_range)
            elif range := request.headers.get('Range'):
                offset, limit = parse_content_range(range)

        elif SERVER.version == TAXII_VER_2_1:
            next = request.args.get('next')
            limit_arg = request.args.get('limit')
            offset = int(next) if next else 0
            limit = int(limit_arg) if limit_arg else 100

        manifest_response, date_added_first, date_added_last = SERVER.get_manifest(
            collection_id=collection_id,
            added_after=added_after,
            offset=offset,
            limit=limit,
            types=types,
        )
    except Exception as e:
        error = f'Could not perform the manifest request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Manifest Request Error',
                                                      'description': error})

    return handle_response(
        status_code=HTTP_200_OK,
        content=manifest_response,
        date_added_first=date_added_first,
        date_added_last=date_added_last,
    )


@APP.route('/<api_root>/collections/<collection_id>/objects/', methods=['GET'])
@taxii_validate_request_headers
@taxii_validate_url_param
def taxii2_objects(api_root: str, collection_id: str):
    """
    Defines TAXII API - Collections Objects:
    Get Collection section (5.4) `here
    <https://docs.oasis-open.org/cti/taxii/v2.1/csprd01/taxii-v2.1-csprd01.html#_Toc532988055>`__
    Args:
        collection_id: collection id to query it objects
        api_root (str): the base URL of the API Root
    Returns:
        envelope: A Envelope Resource upon successful requests. Additional information
        `here <https://docs.oasis-open.org/cti/taxii/v2.1/csprd01/taxii-v2.1-csprd01.html#_Toc532988038>`__.
    """
    try:
        added_after = request.args.get('added_after')
        types = argToList(request.args.get('match[type]'))
        limit = 100
        offset = 0

        if request.args.get('match[id]') or request.args.get('match[version]'):
            raise Exception('Filtering by id or version is not supported.')

        try:
            if added_after:
                datetime.strptime(added_after, STIX_DATE_FORMAT)
        except ValueError as e:
            raise Exception(f'Added after time format should be YYYY-MM-DDTHH:mm:ss.[s+]Z. {e}')

        if SERVER.version == TAXII_VER_2_0:
            if content_range := request.headers.get('Content-Range'):
                offset, limit = parse_content_range(content_range)
            elif range := request.headers.get('Range'):
                offset, limit = parse_content_range(range)

        elif SERVER.version == TAXII_VER_2_1:
            next = request.args.get('next')
            limit_arg = request.args.get('limit')

            offset = int(next) if next else 0
            limit = int(limit_arg) if limit_arg else 100

        objects_response, date_added_first, date_added_last = SERVER.get_objects(
            collection_id=collection_id,
            added_after=added_after,
            offset=offset,
            limit=limit,
            types=types,
        )
    except Exception as e:
        error = f'Could not perform the objects request: {str(e)}'
        handle_long_running_error(error)
        return handle_response(HTTP_400_BAD_REQUEST, {'title': 'Objects Request Error',
                                                      'description': error})

    return handle_response(
        status_code=HTTP_200_OK,
        content=objects_response,
        date_added_first=date_added_first,
        date_added_last=date_added_last,
        content_type=MEDIA_TYPE_STIX_V20 if SERVER.version == TAXII_VER_2_0 else MEDIA_TYPE_TAXII_V21
    )


def test_module(params):
    """
    Integration test module.
    """
    run_long_running(params, is_test=True)
    return 'ok'


def main():
    """
    Main
    """
    global SERVER

    params = demisto.params()
    command = demisto.command()

    try:
        port = int(params.get('longRunningPort'))
    except ValueError as e:
        raise ValueError(f'Invalid listen port - {e}')

    collections = get_collections(params)
    version = params.get('version')
    credentials = params.get('credentials', {})

    server_links = demisto.demistoUrls()
    server_link_parts: ParseResult = urlparse(server_links.get('server'))
    host_name = server_link_parts.hostname

    service_address = params.get('service_address')

    certificate = params.get('certificate', '')
    private_key = params.get('key', '')

    if (certificate and not private_key) or (private_key and not certificate):
        raise ValueError('When using HTTPS connection, both certificate and private key must be provided.')

    http_server = not (certificate and private_key)  # False if (certificate and private_key) else True

    scheme = 'https' if not http_server else 'http'

    if version == TAXII_VER_2_0:
        params['nginx_server_conf'] = NGINX_TAXII2SERVER_CONF

    demisto.debug(f'Command being called is {command}')

    try:
        SERVER = TAXII2Server(scheme, str(host_name), port, collections,
                              certificate, private_key, http_server, credentials, version, service_address)

        if command == 'long-running-execution':
            run_long_running(params)

        elif command == 'test-module':
            return_results(test_module(params))

    except Exception as e:
        err_msg = f'Error in {INTEGRATION_NAME} Integration [{e}]'
        return_error(err_msg)


from NGINXApiModule import *  # noqa: E402

if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()