from html import unescape
from typing import Tuple
from urllib.parse import urlparse, parse_qs, ParseResult, unquote

from CommonServerPython import *

ATP_REGEX = re.compile(r'(https://\w*|\w*)\.safelinks\.protection\.outlook\.com/.*\?url=')
PROOF_POINT_URL_REG = re.compile(r'https://urldefense(?:\.proofpoint)?\.(com|us)/(v[0-9])/')
HTTPS = 'https'
HTTP = 'http'
PREFIX_TO_NORMALIZE = {
    'hxxp',
    'meow',
    'hXXp',
}
# Tuple of starts_with, does_not_start_with (if exists), replace to.
PREFIX_CHANGES: List[Tuple[str, Optional[str], str]] = [
    ('https:/', 'https://', 'https://'),
    ('http:/', 'http://', 'http://'),
    ('https:\\', 'https:\\\\', 'https://'),
    ('http:\\', 'http:\\\\', 'http://'),
    ('https:\\\\', None, 'https://'),
    ('http:\\\\', None, 'http://')
]


def get_redirect_url_proof_point_v2(non_formatted_url: str, parse_results: ParseResult) -> str:
    """
    Extracts redirect URL from Proof Point V2.
    Args:
        non_formatted_url (str): Non formatted URL.
        parse_results (ParseResult): Parse results of the given URL.

    Returns:
        (str): Redirected URL from Proof Point.
    """
    url_: str = get_redirect_url_from_query(non_formatted_url, parse_results, 'u')
    trans = str.maketrans('-_', '%/')
    url_ = url_.translate(trans)
    return url_


def get_redirect_url_proof_point_v3(non_formatted_url: str) -> str:
    """
    Extracts redirect URL from Proof Point V3.
    Args:
        non_formatted_url (str): Non formatted URL.

    Returns:
        (str): Redirected URL from Proof Point.
    """
    url_regex = re.compile(r'v3/__(?P<url>.+?)__;(?P<enc_bytes>.*?)!')
    if match := url_regex.search(non_formatted_url):
        non_formatted_url = match.group('url')
    else:
        demisto.error(f'Could not parse Proof Point redirected URL. Returning original URL: {non_formatted_url}')
    return non_formatted_url


def get_redirect_url_from_query(non_formatted_url: str, parse_results: ParseResult, redirect_param_name: str) -> str:
    """
    Receives an ATP Safe Link URL, returns the URL the ATP Safe Link points to.
    Args:
        non_formatted_url (str): The raw URL. For debugging purposes.
        parse_results (str): ATP Safe Link URL parse results.
        redirect_param_name (str): Name of the redirect parameter.
    Returns:
        (str): The URL the ATP Safe Link points to.
    """
    query_params_dict: Dict[str, List[str]] = parse_qs(parse_results.query)
    if not (query_urls := query_params_dict.get(redirect_param_name, [])):
        demisto.error(f'Could not find redirected URL. Returning the original URL: {non_formatted_url}')
        return non_formatted_url
    if len(query_urls) > 1:
        demisto.debug(f'Found more than one URL query parameters for redirect in the given URL {non_formatted_url}\n'
                      f'Returning the first URL: {query_urls[0]}')
    url_: str = query_urls[0]
    return url_


def replace_protocol(url_: str) -> str:
    """
    Replaces URL protocol with expected protocol.
    Examples:
    1)  http:/www.test.com
        > http://www.test.com
    2)  https:/www.test.com
        > https://www.test.com
    3)  http:\\www.test.com
        > http://www.test.com
    4)  https:\\www.test.com
        > https://www.test.com
    5)  http:\www.test.com
        > http://www.test.com
    6)  https:\www.test.com
        > https://www.test.com
    7)  hxxp://www.test.com
        > http://www.test.com
    8)  hXXp://www.test.com
        > http://www.test.com
    9)  hxxps://www.test.com
        > https://www.test.com
    10)  hXXps://www.test.com
        > https://www.test.com
    Args:
        url_ (str): URL to replace the protocol by the given examples above.

    Returns:
        (str): URL with replaced protocol, if needed to replace, else the URL itself.
    """
    for prefix_to_normalize in PREFIX_TO_NORMALIZE:
        if url_.startswith(prefix_to_normalize):
            url_ = url_.replace(prefix_to_normalize, 'http')
    lowercase_url = url_.lower()
    for starts_with, does_not_start_with, to_replace in PREFIX_CHANGES:
        if lowercase_url.startswith(starts_with) and (
                not does_not_start_with or not lowercase_url.startswith(does_not_start_with)):
            url_ = url_.replace(starts_with, to_replace)
    return url_


def normalize_url(non_normalized_url: str) -> str:
    """
    Normalizes a URL.
    Args:
        non_normalized_url (str): URL to normalize.

    Returns:
        (str): Normalized URL.
    """
    non_normalized_url = unescape(non_normalized_url.replace('[.]', '.'))
    return non_normalized_url


def format_url(non_formatted_url: str) -> str:
    """
    Formats a single URL.
    Args:
        non_formatted_url (str): Non formatted URL.

    Returns:
        (str): Formatted URL.
    """
    parse_results: ParseResult = urlparse(non_formatted_url)
    # ATP redirect URL
    if re.match(ATP_REGEX, non_formatted_url):
        non_formatted_url = get_redirect_url_from_query(non_formatted_url, parse_results, 'url')
    elif match := PROOF_POINT_URL_REG.search(non_formatted_url):
        proof_point_ver: str = match.group(2)
        if proof_point_ver == 'v3':
            non_formatted_url = get_redirect_url_proof_point_v3(non_formatted_url)
        elif proof_point_ver == 'v2':
            non_formatted_url = get_redirect_url_proof_point_v2(non_formatted_url, parse_results)
        else:
            non_formatted_url = get_redirect_url_from_query(non_formatted_url, parse_results, 'u')
    # Common handling for unescape and normalizing
    non_formatted_url = unquote(unescape(non_formatted_url.replace('[.]', '.')))
    formatted_url = replace_protocol(non_formatted_url)

    return formatted_url


def main():
    try:
        non_formatted_urls: List[str] = [url_.trim() for url_ in argToList(demisto.args().get('input'))]
        return_results(CommandResults(outputs=non_formatted_urls))
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute ExtractURL. Error: {str(e)}')


''' ENTRY POINT '''

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
