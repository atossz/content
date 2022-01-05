"""Base Integration for Cortex XSOAR (aka Demisto)

This is an empty Integration with some basic structure according
to the code conventions.

MAKE SURE YOU REVIEW/REPLACE ALL THE COMMENTS MARKED AS "TODO"

Developer Documentation: https://xsoar.pan.dev/docs/welcome
Code Conventions: https://xsoar.pan.dev/docs/integrations/code-conventions
Linting: https://xsoar.pan.dev/docs/integrations/linting

This is an empty structure file. Check an example at;
https://github.com/demisto/content/blob/master/Packs/HelloWorld/Integrations/HelloWorld/HelloWorld.py

"""

import demistomock as demisto
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
import requests
import traceback
from typing import Dict, Any

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()  # pylint: disable=no-member

DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'  # ISO8601 format with UTC, default in XSOAR
SEARCH_TERM_QUERY_ARGS = ('file_name', 'file_type', 'file_type_desc', 'env_id', 'country', 'verdict', 'av_detect',
                          'vx_family', 'tag', 'date_from', 'date_to', 'port', 'host', 'domain', 'url', 'similiar_to',
                          'context', 'imp_hash', 'ssdeep', 'authentihash')


class Client(BaseClient):

    def get_environments(self):
        return self._http_request(method='GET', url_suffix='/system/environments')

    def get_screenshots(self, key):
        return self._http_request(method='GET', url_suffix=f"/report/{key}/screenshots")

    def search(self, query_args: Dict[str, Any]):
        pass


def translate_verdict(param: str):
    if param.isnumeric():  # TODO does this come in as a string?
        return param
    return {
        'Whitelisted': 1,
        'NoVerdict': 2,
        'NoSpecificThreat': 3,
        'Suspicious': 4,
        'Malicious': 4
    }[param]


def split_query_to_term_args(query: str) -> Dict[str, Any]:
    pass


def validated_term(pair):
    if pair[0] == 'verdict':
        return translate_verdict(pair[1])
    if pair[0] == 'country' and len(pair[1]) != 3:
        raise ValueError('Country ISO code should be 3 characters long')
    return pair[1]


def validated_search_terms(query_args: Dict[str, Any]) -> Dict[str, Any]:
    if len(query_args) == 0:
        raise ValueError('Must have at least one search term')
    return {pair[0]: validated_term(pair) for pair in query_args}


def get_search_term_args(args) -> Dict[str, Any]:
    if args['query']:
        return split_query_to_term_args(args['query'])
    else:
        return {term: args[term] for term in SEARCH_TERM_QUERY_ARGS if args[term]}


def to_image_result(image):
    return fileResult(image['name'], base64.b64decode(image['image']), entryTypes['entryInfoFile'])


def get_key(args):
    if args['file'] and args['environmentID']:
        return f"{args['file']}:{args['environmentID']}"
    elif args['jobID']:
        return args['jobID']
    else:
        raise ValueError('Must supply job_id or environment_id and file')


def test_module(client: Client) -> str:
    """Tests API connectivity and authentication'

    Returning 'ok' indicates that the integration works like it is supposed to.
    Connection to the service is successful.
    Raises exceptions if something goes wrong.

    :type client: ``Client``
    :param Client: client to use

    :return: 'ok' if test passed, anything else will fail the test.
    :rtype: ``str``
    """

    message: str = ''
    try:
        # TODO: ADD HERE some code to test connectivity and authentication to your service.
        # This  should validate all the inputs given in the integration configuration panel,
        # either manually or by using an API that uses them.
        message = 'ok'
    except DemistoException as e:
        if 'Forbidden' in str(e) or 'Authorization' in str(e):  # TODO: make sure you capture authentication errors
            message = 'Authorization Error: make sure API Key is correctly set'
        else:
            raise e
    return message


def crowdstrike_get_environments_command(client: Client):
    environments = client.get_environments()
    demisto.info(environments)
    return CommandResults(
        outputs_prefix='CrowdStrike.Environment',
        outputs_key_field='id',
        outputs=environments,
        readable_output=tableToMarkdown('All Environments:', environments, ['id', 'description'],
                                        headerTransform=lambda x: {'id': '_ID', 'description': 'Description'}[x]),
        raw_response=environments
    )


def crowdstrike_get_screenshots_command(client: Client, args: Dict[str, Any]):
    key = get_key(args)
    return [to_image_result(image) for image in client.get_screenshots(key)]


def crowdstrike_result_command():
    pass


def crowdstrike_search_command(client: Client, args):
    query_args: Dict = get_search_term_args(args)
    query_args = validated_search_terms(query_args)

    return client.search(query_args)


def main() -> None:
    """main function, parses params and runs command functions

    :return:
    :rtype:
    """
    params: Dict[str, Any] = demisto.params()
    args: Dict[str, Any] = demisto.args()
    # if your Client class inherits from BaseClient, SSL verification is
    # handled out of the box by it, just pass ``verify_certificate`` to
    # the Client constructor
    verify_certificate = not params.get('insecure', False)

    # if your Client class inherits from BaseClient, system proxy is handled
    # out of the box by it, just pass ``proxy`` to the Client constructor
    proxy = params.get('proxy', False)

    demisto.debug(f'Command being called is {demisto.command()}')
    try:
        headers: Dict = {
            'api-key': demisto.params().get('credentials', {}).get('password'),
            'User-Agent': 'Falcon Sandbox'
        }

        client = Client(
            base_url=demisto.params()['serverUrl'],
            verify=verify_certificate,
            headers=headers,
            proxy=proxy)

        if demisto.command() == 'test-module':
            # This is the call made when pressing the integration Test button.
            result = test_module(client)
            return_results(result)

        elif demisto.command() in ('crowdstrike-get-environments', 'cs-falcon-sandbox-get-environments'):
            return_results(crowdstrike_get_environments_command(client))
        elif demisto.command() in ('cs-falcon-sandbox-get-screenshots', 'crowdstrike-get-screenshots'):
            demisto.results(crowdstrike_get_screenshots_command(client, args))
        elif demisto.command() in ('cs-falcon-sandbox-result', 'crowdstrike-result'):
            crowdstrike_result_command()
        elif demisto.command() in ('cs-falcon-sandbox-search', 'crowdstrike-search'):
            crowdstrike_search_command(client, args)

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute {demisto.command()} command.\nError:\n{str(e)}')


''' ENTRY POINT '''

# if __name__ in ('__main__', '__builtin__', 'builtins'): TODO return line
main()
