import os
import io
import sys
import luigi
import luigi.contrib.hdfs
import luigi.contrib.hadoop
import urlparse
import hanzo, hanzo.warctools
from hanzo.warctools import WarcRecord
try:
    from http.client import HTTPResponse
except ImportError:
    from httplib import HTTPResponse


class ExternalListFile(luigi.ExternalTask):
    """
    This ExternalTask defines the Target at the top of the task chain. i.e. resources that are overall inputs rather
    than generated by the tasks themselves.
    """
    input_file = luigi.Parameter()

    def output(self):
        """
        Returns the target output for this task.
        In this case, it expects a file to be present in HDFS.
        :return: the target output for this task.
        :rtype: object (:py:class:`luigi.target.Target`)
        """
        return luigi.contrib.hdfs.HdfsTarget(self.input_file)


class GenerateWarcStatsIndirect(luigi.contrib.hadoop.JobTask):
    """
    Generates the WARC stats by reading each file in turn. Data is therefore no-local.

    Parameters:
        input_file: The file (on HDFS) that contains the list of WARC files to process
    """
    input_file = luigi.Parameter()

    def output(self):
        out_name = "%s-stats.tsv" % os.path.splitext(self.input_file)[0]
        return luigi.contrib.hdfs.HdfsTarget(out_name, format=luigi.contrib.hdfs.PlainDir)

    def requires(self):
        return ExternalListFile(self.input_file)

    def extra_modules(self):
        return []

    def extra_files(self):
        return ["luigi.cfg"]

    def mapper(self, line):
        """
        Each line should be a path to a WARC file on HDFS

        We open each one in turn, and scan the contents.

        The pywb record parser gives access to the following properties (at least):

        entry['urlkey']
        entry['timestamp']
        entry['url']
        entry['mime']
        entry['status']
        entry['digest']
        entry['length']
        entry['offset']

        :param line:
        :return:
        """

        # Ignore blank lines:
        if line == '':
            return

        warc = luigi.contrib.hdfs.HdfsTarget(line)
        #entry_iter = DefaultRecordParser(sort=False,
        #                                 surt_ordered=True,
       ##                                  include_all=False,
        #                                 verify_http=False,
        #                                 cdx09=False,
        #                                 cdxj=False,
        #                                 minimal=False)(warc.open('rb'))

        #for entry in entry_iter:
        #    hostname = urlparse.urlparse(entry['url']).hostname
        #    yield hostname, entry['status']

    def reducer(self, key, values):
        """

        :param key:
        :param values:
        :return:
        """
        for value in values:
            yield key, sum(values)


class ExternalFilesFromList(luigi.ExternalTask):
    """
    This ExternalTask defines the Target at the top of the task chain. i.e. resources that are overall inputs rather
    than generated by the tasks themselves.
    """
    input_file = luigi.Parameter()

    def output(self):
        """
        Returns the target output for this task.
        In this case, it expects a file to be present in HDFS.
        :return: the target output for this task.
        :rtype: object (:py:class:`luigi.target.Target`)
        """
        for line in open(self.input_file, 'r').readlines():
            yield luigi.contrib.hdfs.HdfsTarget(line.strip(), format=luigi.contrib.hdfs.format.PlainFormat)


class GenerateWarcStats(luigi.contrib.hadoop.JobTask):
    """
    Generates the Warc stats by reading in each file and splitting the stream into entries.

    As this uses the stream directly and so data-locality is preserved.

    Parameters:
        input_file: The file (on HDFS) that contains the list of WARC files to process
    """
    input_file = luigi.Parameter()

    input_format = "uk.bl.wa.hadoop.mapreduce.hash.UnsplittableInputFileFormat"

    def output(self):
        out_name = "%s-stats.tsv" % os.path.splitext(self.input_file)[0]
        return luigi.contrib.hdfs.HdfsTarget(out_name, format=luigi.contrib.hdfs.PlainDir)

    def requires(self):
        return ExternalFilesFromList(self.input_file)

    def extra_files(self):
        return ["luigi.cfg"]

    def extra_modules(self):
        return [hanzo]

    def libjars(self):
        return ["../jars/warc-hadoop-recordreaders-2.2.0-BETA-7-SNAPSHOT-job.jar"]

    def run_mapper(self, stdin=sys.stdin, stdout=sys.stdout):
        """
        Run the mapper on the hadoop node.
        ANJ: Creating modified version to pass through the raw stdin
        """
        self.init_hadoop()
        self.init_mapper()
        outputs = self._map_input(stdin)
        if self.reducer == NotImplemented:
            self.writer(outputs, stdout)
        else:
            self.internal_writer(outputs, stdout)

    def reader(self, stdin):
        # Special reader to read the input stream and yield WARC records:
        class TellingReader():

            def __init__(self, stream):
                self.stream = io.BufferedReader(stream)

            def read(self, size=None):
                chunk = self.stream.read(size=size)
                return chunk

            def seek(self, *args, **kwargs):
                return self.stream.seek(args, kwargs)

            def tell(self):
                return 0

        fh = hanzo.warctools.WarcRecord.open_archive(filename="dummy.warc.gz",
                                                     file_handle=TellingReader(stdin))

        for (offset, record, errors) in fh.read_records(limit=None):
            if record:
                yield record

    def mapper(self, record):
        """

        :param record:
        :return:
        """

        # Look at HTTP Responses:
        if (record.type == WarcRecord.RESPONSE
                and record.content_type.startswith(b'application/http')):
            # Parse the HTTP Headers:
            f = HTTPResponse(record.content_file)
            f.begin()

            hostname = urlparse.urlparse(record.url).hostname
            yield hostname, f.status

    def reducer(self, key, values):
        """

        :param key:
        :param values:
        :return:
        """
        for value in values:
            yield key, sum(values)


if __name__ == '__main__':
    luigi.run(['GenerateWarcStats', '--input-file', 'daily-warcs-test.txt', '--local-scheduler'])
