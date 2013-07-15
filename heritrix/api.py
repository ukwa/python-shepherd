import sys
import logging
import requests
import xml.etree.ElementTree as ET
from requests.auth import HTTPDigestAuth

requests_log = logging.getLogger( "requests" )
requests_log.setLevel( logging.WARNING )

class API(object):


	def __init__(self, host='https://localhost:8443/engine',
		user='admin', passwd='', verbose=False, verify=False):
		self.host = host
		self.user = user
		self.passwd = passwd
		self.config = {}
		if verbose:
			self.config['verbose'] = sys.stderr
		self.verify = verify

	def _get(self, url=''):
		headers = {'Accept': 'application/xml'}
		r = requests.get(url, auth=HTTPDigestAuth(self.user, self.passwd), headers=headers, config=self.config, verify=self.verify)
		return r

	def _post(self, action='', url='', data={}):
		if action == '':
			return None
		if not url:
			url = self.host
		data['action'] = action
		headers = {'Accept': 'application/xml'}
		r = requests.post(url, auth=HTTPDigestAuth(self.user, self.passwd),
			data=data, headers=headers, config=self.config,
			verify=self.verify)
		return r

	def add(self, addpath=''):
		action = 'add'
		if addpath == '':
			return None
		return self._post(action, data={'addpath': addpath})

	def create(self, createpath=''):
		action = 'create'
		if createpath == '':
			return None
		return self._post(action, data={'createpath': createpath})

	def rescan(self):
		action = 'rescan'
		return self._post(action)

	def _job_action(self, action='', job=''):
		if action == '' and job == '':
			return self._get(url=self.host)
		else:
			url = '%s/job/%s' % (self.host, job)
			if action == '':
				return self._get(url=url)
			else:
				return self._post(action=action, url=url)

	def build(self, job=''):
		return self._job_action(action='build', job=job)

	def launch(self, job=''):
		return self._job_action(action='launch', job=job)
		
	def pause(self, job=''):
		return self._job_action(action='pause', job=job)

	def unpause(self, job=''):
		return self._job_action(action='unpause', job=job)

	def terminate(self, job=''):
		return self._job_action(action='terminate', job=job)

	def teardown(self, job=''):
		return self._job_action(action='teardown', job=job)

	def checkpoint(self, job=''):
		return self._job_action(action='checkpoint', job=job)

	def copy(self, copyTo='', asProfile=False):
		if copyTo == '':
			return None
		url = '%s/job/%s' % (self.host, job)
		data = {'copyTo': copyTo}
		if asProfile:
			data['asProfile'] = 'on'
		else:
			data['asProfile'] = 'off'
		headers = {'Accept': 'application/xml'}
		r = requests.post(url=url, auth=(self.user, self.passwd),
			data=data, headers=headers, config=self.config,
			verify=self.verify)
		return r

	def submit(self, job='', urls=[], config={}):
		# NOTE: is a PUT.
		# FIXME: hmm, what would be useful here?
		#r = requests.post(url=url, auth=(self.user, self.passwd),
		#	verify=self.verify)
		return

	def status(self, job=''):
		xml = ET.fromstring( self._job_action(action='',job=job).text )
		status = xml.find("crawlControllerState")
		if status == None:
			return ''
		else:
			return status.text

	def listjobs(self):
		xml = ET.fromstring( self._job_action(action='',job='').text )
		jobs = xml.find("jobs")
		shortNames = []
		for job in jobs:
			shortNames.append(job.find("shortName").text)
		return shortNames

	def execute(self, engine="beanshell", script="", job=""):
		if script == "":
			return None
		url = "%s/job/%s/script" % (self.host, job)
		return self._post(url=url, action="execute", data={"engine": engine, "script": script})
