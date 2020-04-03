'''
This contains the core TrackDB code for managing queries and updates to the Tracking Database
'''
import os
import json
import logging
import argparse
from lib.trackdb.solr import SolrTrackDB

logger = logging.getLogger(__name__)

# Defaults to using the DEV TrackDB Solr backend:
DEFAULT_TRACKDB = os.environ.get("TRACKDB_URL","http://trackdb.dapi.wa.bl.uk/solr/tracking")

def main():
    # Set up a parser:
    parser = argparse.ArgumentParser(prog='trackdb')

    # Common arguments:
    parser.add_argument('-t', '--trackdb-url', type=str, help='The TrackDB URL to talk to (defaults to %s).' % DEFAULT_TRACKDB, 
        default=DEFAULT_TRACKDB)
    parser.add_argument('--dry-run', action='store_true', help='Do not modify the TrackDB.')
    parser.add_argument('-i', '--indent', type=int, help='Number of spaces to indent when emitting JSON.')
    parser.add_argument('--filter-by-stream', 
        choices= ['frequent', 'domain', 'webrecorder'], 
        help='Filter the results by stream.', default='[* TO *]')
    parser.add_argument('--filter-by-collection', 
        choices= ['npld', 'bypm'], 
        help='Filter the results by the collection, NPLD or by-permission.', default='[* TO *]')
    parser.add_argument('--filter-by-year', 
        type=int,
        help='Filter down by date.')
    parser.add_argument('--filter-by-field', 
        type=str,
        help='Filter by any additional field and value, in the form field:value.')
    parser.add_argument('kind', 
        choices= ['warcs', 'logs', 'launches'], 
        help='The kind of thing to track.', default='[* TO *]')

    # Use sub-parsers for different operations:
    subparsers = parser.add_subparsers(dest="op")

    # Add a parser for the 'get' subcommand:
    parser_get = subparsers.add_parser('get', help='Get a single record from the TrackDB.')
    parser_get.add_argument('id', type=str, help='The id to look up.')

    # Add a parser for the 'list' subcommand:
    parser_list = subparsers.add_parser('list', help='Get a list of records from the TrackDB.')
    parser_list.add_argument('--limit', type=int, default=10, help='The maximum number of records to return.')

    # Add a parser for the 'update' subcommand:
    parser_up = subparsers.add_parser('update', help='Create or update on a record in the TrackDB.')
    parser_up.add_argument('--set', metavar=('field','value'), help='Set a field to a given value.', nargs=2)
    parser_up.add_argument('--add', metavar=('field','value'), help='Add the given value to a field. Always uses add-distinct', nargs=2)
    parser_up.add_argument('--remove', metavar=('field','value'), help='Remove the specified value from the field.', nargs=2)
    parser_up.add_argument('--inc', metavar=('field','increment'), help='Increment the specified field, e.g. "--inc counter 1".', nargs=2)
    parser_up.add_argument('id', type=str, help='The record ID to use.')

# trackdb warcs update --set cdx_index_ss data-heritrix_unverified hdfs://identifier
# trackdb warcs update --remove cdx_index_ss data-heritrix_unverified --set cdx_index_ss data-heritrix hdfs://identifier

    # And PARSE it:
    args = parser.parse_args()

    # Set up Solr client:
    tdb = SolrTrackDB(args.trackdb_url, kind=args.kind)

    # Ops:
    logger.info("Got args: %s" % args)
    if args.op == 'list':
        docs = tdb.list(args.filter_by_stream, args.filter_by_year, args.filter_by_field)
        print(json.dumps(docs, indent=args.indent))
    elif args.op == 'get':
        doc = tdb.get(args.id)
        print(json.dumps(doc, indent=args.indent))
    elif args.op == 'update':
        if args.set:
            tdb.update(args.id, args.set[0], args.set[1], action='set')
        if args.add:
            tdb.update(args.id, args.add[0], args.add[1])
        if args.remove:
            tdb.update(args.id, args.remove[0], args.remove[1], action='remove')
        if args.inc:
            tdb.update(args.id, args.inc[0], args.inc[1], action='remove')
    else:
        raise Exception("Not implemented!")


if __name__ == "__main__":
    main()
