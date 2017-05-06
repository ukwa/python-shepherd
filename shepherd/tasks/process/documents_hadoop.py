import re
import os
import json
import logging
from urlparse import urlparse
import luigi.contrib.hdfs
import luigi.contrib.hadoop
from luigi.contrib.hdfs.format import Plain, PlainDir

import shepherd # Imported so extra_modules MR-bundle can access the following:
from shepherd.lib.h3.utils import url_to_surt

logger = logging.getLogger(__name__)


class LogFilesForJobLaunch(luigi.ExternalTask):
    """
    On initialisation, looks up all logs current on HDFS for a particular job.

    Emits list of files to be processed.

    No run() as depends on external processes that produce the logs.
    """
    task_namespace = 'scan'
    job = luigi.Parameter()
    launch_id = luigi.Parameter()

    def output(self):
        outputs = []
        # Get HDFS client:
        client = luigi.contrib.hdfs.WebHdfsClient()
        parent_path = "/heritrix/output/logs/%s/%s" % (self.job, self.launch_id)
        for listed_item in client.listdir(parent_path):
            # Oddly, depending on the implementation, the listed_path may be absolute or basename-only, so fix here:
            item = os.path.basename(listed_item)
            item_path = os.path.join(parent_path, item)
            if item.endswith(".lck"):
                logger.error("Lock file should be be present on HDFS! %s" % (item, item_path))
                pass
            elif item.startswith("crawl.log"):
                outputs.append(luigi.contrib.hdfs.HdfsTarget(path=item_path, format=Plain))
                logger.debug("Including %s" % item)
            else:
                pass
                #logger.debug("Skipping %s" % item)
        # Return the logs to be processed:
        return outputs


class HdfsFile(luigi.ExternalTask):
    """
    This ExternalTask defines the Target at the top of the task chain. i.e. resources that are overall inputs rather
    than generated by the tasks themselves.
    """
    hdfs_path = luigi.Parameter()

    def output(self):
        """
        Returns the target output for this task.
        In this case, it expects a file to be present in HDFS.
        :return: the target output for this task.
        :rtype: object (:py:class:`luigi.target.Target`)
        """
        return luigi.contrib.hdfs.HdfsTarget(path=self.hdfs_path)


class ScanLogFileForDocs(luigi.contrib.hadoop.JobTask):
    """
    Map-Reduce job that scans a log file for documents associated with 'Watched' targets.

    Should run locally if run with only local inputs.

    Input:

    {
        "annotations": "ip:173.236.225.186,duplicate:digest",
        "content_digest": "sha1:44KA4PQA5TYRAXDIVJIAFD72RN55OQHJ",
        "content_length": 324,
        "extra_info": {},
        "hop_path": "IE",
        "host": "acid.matkelly.com",
        "jobName": "frequent",
        "mimetype": "text/html",
        "seed": "WTID:12321444",
        "size": 511,
        "start_time_plus_duration": "20160127211938966+230",
        "status_code": 404,
        "thread": 189,
        "timestamp": "2016-01-27T21:19:39.200Z",
        "url": "http://acid.matkelly.com/img.png",
        "via": "http://acid.matkelly.com/",
        "warc_filename": "BL-20160127211918391-00001-35~ce37d8d00c1f~8443.warc.gz",
        "warc_offset": 36748
    }

    Note that 'seed' is actually the source tag, and is set up to contain the original (Watched) Target ID.

    Output:

    [
    {
    "id_watched_target":<long>,
    "wayback_timestamp":<String>,
    "landing_page_url":<String>,
    "document_url":<String>,
    "filename":<String>,
    "size":<long>
    },
    <further documents>
    ]

    See https://github.com/ukwa/w3act/wiki/Document-REST-Endpoint

    i.e.

    seed -> id_watched_target
    start_time_plus_duration -> wayback_timestamp
    via -> landing_page_url
    url -> document_url (and filename)
    content_length -> size

    Note that, if necessary, this process to refer to the
    cdx-server and wayback to get more information about
    the crawled data and improve the landing page and filename data.


    """

    task_namespace = 'doc'
    job = luigi.Parameter()
    launch_id = luigi.Parameter()
    watched_surts = luigi.ListParameter()
    log_path = luigi.Parameter()

    n_reduce_tasks = 1 # This is set to 1 as there is intended to be one output file.

    def requires(self):
        logger.info("WATCHED SURTS: %s" % self.watched_surts)
        logger.info("LOG FILE TO PROCESS: %s" % self.log_path)
        return HdfsFile(self.log_path)

    def output(self):
        out_name = "task-state/%s/%s/%s.docs" % (self.job, self.launch_id, os.path.basename(self.log_path))
        return luigi.contrib.hdfs.HdfsTarget(path=out_name, format=PlainDir)

    def extra_modules(self):
        return [shepherd]

    def jobconfs(self):
        """
        Also override number of mappers.

        :return:
        """
        jcs = super(ScanLogFileForDocs, self).jobconfs()
        jcs.append('mapred.map.tasks=%s' % 100)
        #jcs.append('mapred.min.split.size', ) mapred.max.split.size, in bytes. e.g. 256*1024*1024 = 256M
        return jcs

    def mapper(self, line):
        (timestamp, status_code, content_length, url, hop_path, via, mime,
         thread, start_time_plus_duration, hash, source, annotations) = re.split(" +", line, maxsplit=11)
        # Skip non-downloads:
        if status_code == '-' or status_code == '' or int(status_code) / 100 != 2:
            return
        # Check the URL and Content-Type:
        if "application/pdf" in mime:
            for prefix in self.watched_surts:
                document_surt = url_to_surt(url)
                landing_page_surt = url_to_surt(via)
                # Are both URIs under the same watched SURT:
                if document_surt.startswith(prefix) and landing_page_surt.startswith(prefix):
                    logger.info("Found document: %s" % line)
                    # Proceed to extract metadata and pass on to W3ACT:
                    doc = {
                        'wayback_timestamp': start_time_plus_duration[:14],
                        'landing_page_url': via,
                        'document_url': url,
                        'filename': os.path.basename(urlparse(url).path),
                        'size': int(content_length),
                        # Add some more metadata to the output so we can work out where this came from later:
                        'job_name': self.job,
                        'launch_id': self.launch_id,
                        'source': source
                    }
                    logger.info("Found document: %s" % doc)
                    yield url, json.dumps(doc)

    def reducer(self, key, values):
        """
        A pass-through reducer.

        :param key:
        :param values:
        :return:
        """
        for value in values:
            yield key, value


if __name__ == '__main__':
    luigi.run(['doc.ExtractDocuments', '--job', 'weekly', '--launch-id', '20170220090024', '--local-scheduler'])
    #luigi.run(['scan.ScanForDocuments', '--date-interval', '2017-02-10-2017-02-12', '--local-scheduler'])
