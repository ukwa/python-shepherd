#!/usr/bin/env python

"""Daemon which watches a configured queue for messages and for each, calls a
webservice, storing the result in a WARC file."""

import os
import sys
import pika
import uuid
import shutil
import logging
import requests
import settings
from daemonize import Daemon
from datetime import datetime
from hanzo.warctools import WarcRecord
from warcwriterpool import WarcWriterPool
from hanzo.warctools.warc import warc_datetime_str

logger = logging.getLogger( "harchiverd" )
handler = logging.FileHandler( settings.LOG_FILE )
formatter = logging.Formatter( "[%(asctime)s] %(levelname)s: %(message)s" )
handler.setFormatter( formatter )
logger.addHandler( handler )
logger.setLevel( logging.DEBUG )

#Try to set logging output for all modules.
logging.root.setLevel( logging.DEBUG )
logging.getLogger( "" ).addHandler( handler )


def callback( warcwriter, body ):
	"""Passed a URL, passes that URL to a webservice, storing the
	return content in a WARC file."""
	try:
		logger.debug( "Message received: %s." % body )
		if "|" in body:
			#Old-style messages
			url, dir = body.split( "|" )
		else:
			url = body
		ws = "%s/%s" % ( settings.WEBSERVICE, url )
		logger.debug( "Calling %s" % ws )
		har = requests.get( ws ).content
		headers = [
			( WarcRecord.TYPE, WarcRecord.METADATA ),
			( WarcRecord.URL, url ),
			( WarcRecord.CONTENT_TYPE, "application/json" ),
			( WarcRecord.DATE, warc_datetime_str( datetime.now() ) ),
			( WarcRecord.ID, "<urn:uuid:%s>" % uuid.uuid1() ),
		]
		warcwriter.write_record( headers, "application/json", har )
	except Exception as e:
		logger.error( "%s [%s]" % ( str( e ), body ) )

class HarchiverDaemon( Daemon ):
	"""Maintains a connection to the queue."""
	def run( self ):
		warcwriter = WarcWriterPool( gzip=True, output_dir=settings.OUTPUT_DIRECTORY )
		while True:
			try:
				logger.debug( "Starting connection %s:%s." % ( settings.HAR_QUEUE_HOST, settings.HAR_QUEUE_NAME ) )
				connection = pika.BlockingConnection( pika.ConnectionParameters( settings.HAR_QUEUE_HOST ) )
				channel = connection.channel()
				channel.queue_declare( queue=settings.HAR_QUEUE_NAME, durable=True )
				for method_frame, properties, body in channel.consume( settings.HAR_QUEUE_NAME ):
					callback( warcwriter, body )
					channel.basic_ack( method_frame.delivery_tag )
			except Exception as e:
				logger.error( str( e ) )
				requeued_messages = channel.cancel()
				logger.debug( "Requeued %i messages" % requeued_messages )
 
if __name__ == "__main__":
	"""Sets up the daemon."""
	if len( sys.argv ) == 2:
		daemon = HarchiverDaemon( settings.PID_FILE )
	elif len( sys.argv ) == 3:
		#Possibly pass a PID file to enable multiple instances.
		daemon = HarchiverDaemon( sys.argv[ 2 ] )
	logger.debug( "Arguments: %s" % sys.argv )
	if len( sys.argv ) == 2:
		if "start" == sys.argv[ 1 ]:
			logger.info( "Starting harchiverd." )
			daemon.start()
		elif "stop" == sys.argv[ 1 ]:
			logger.info( "Stopping harchiverd." )
			daemon.stop()
		elif "restart" == sys.argv[ 1 ]:
			logger.info( "Restarting harchiverd." )
			daemon.restart()
		else:
			print "Unknown command"
			print "usage: %s start|stop|restart" % sys.argv[ 0 ]
			sys.exit( 2 )
		logger.debug( "Exiting." )
		sys.exit( 0 )
	else:
		print "usage: %s start|stop|restart" % sys.argv[ 0 ]
		sys.exit( 2 )
