import os
import re
import csv
import enum
import json
import gzip
import glob
import shutil
import logging
import datetime
import luigi
import luigi.contrib.hdfs
import luigi.contrib.webhdfs
import psycopg2
from psycopg2.extras import execute_values
from tasks.analyse.hdfs_path_parser import HdfsPathParser, CrawlStream
from tasks.analyse.hdfs_analysis import CopyFileListToHDFS, ListAllFilesOnHDFSToLocalFile
from tasks.common import state_file
from lib.webhdfs import webhdfs
from lib.targets import AccessTaskDBTarget

logger = logging.getLogger('luigi-interface')

"""
Tasks relating to using the list of HDFS content to update access systems.
"""


class CurrentHDFSFileList(luigi.ExternalTask):
    """
    This is the file on HDFS to look for, generated by an independent task:
    """
    date = luigi.DateParameter(default=datetime.date.today())
    task_namespace = 'access.hdfs'

    def output(self):
        t = CopyFileListToHDFS(self.date).output()
        logger.info("Looking for %s on HDFS..." % t.path)
        return t


class DownloadHDFSFileList(luigi.Task):
    """
    This downloads the HDFS file to a local copy for processing.
    """
    date = luigi.DateParameter(default=datetime.date.today())
    task_namespace = 'access.hdfs'

    def requires(self):
        return CurrentHDFSFileList(self.date)

    def output(self):
        return state_file(None,'access-hdfs','all-files-list.csv', on_hdfs=False)

    def dated_state_file(self):
        return state_file(self.date,'access-hdfs','all-files-list.csv.gz', on_hdfs=False)

    def complete(self):
        # Check the dated file exists
        dated_target = self.dated_state_file()
        logger.info("Checking %s exists..." % dated_target.path)
        exists = dated_target.exists()
        logger.info("Got %s exists = %s..." % (dated_target.path, exists))
        if not exists:
            return False
        return True

    def run(self):
        # Use Luigi's helper to ensure the dated file only appears when all is well:
        with self.dated_state_file().temporary_path() as temp_output_path:

            # Download the file to the dated, compressed file (at a temporary path):
            logger.info("Downloading %s" % self.dated_state_file().path)
            logger.info("Using temp path %s" % temp_output_path)
            client = webhdfs()
            with client.read(self.input().path) as f_in, open(temp_output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            logger.info("Downloaded %s" % self.dated_state_file().path)
            logger.info("Using temp path %s" % temp_output_path)

            # Also make an uncompressed version:
            logger.info("Decompressing %s" % self.dated_state_file().path)
            logger.info("Using temp path %s" % temp_output_path)
            with gzip.open(temp_output_path, 'rb') as f_in, open(self.output().path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            logger.info("Decompressed %s" % self.dated_state_file().path)
            logger.info("Using temp path %s" % temp_output_path)


class UpdateWarcsDatabase(luigi.Task):
    """
    Lists the WARCS and arranges them by date:
    """
    date = luigi.DateParameter(default=datetime.date.today())
    task_namespace = 'access.update'

    total = 0

    def requires(self):
        return DownloadHDFSFileList(self.date)

    #def complete(self):
    #    return False

    def output(self):
        return AccessTaskDBTarget(self.task_namespace, self.task_id)

    def entry_generator(self, reader):
        refresh_date = datetime.datetime.utcnow().isoformat()
        for item in reader:
            # Parse file paths and names:
            p = HdfsPathParser(item)
            # Look at WARCS:
            if p.kind == 'warcs' and p.file_name.endswith(".warc.gz"):
                f_timestamp = None
                if p.timestamp:
                    f_timestamp = p.timestamp
                self.total += 1
                yield (p.file_name, p.job, p.launch, p.file_path, p.file_ext, p.file_size, p.kind, f_timestamp, refresh_date)

    def run(self):
        print("Connect")
        # Set up a DB connection for this:
        conn = psycopg2.connect("dbname=ukwa_manage user=root host=bigcdx port=26257")

        # Make each statement commit immediately.
        conn.set_session(autocommit=True)
        cur = conn.cursor()

        # Go through the data and assemble the resources for each crawl:
        self.total = 0
        print("open up")
        with self.input().open('r') as fin:
            reader = csv.DictReader(fin, fieldnames=ListAllFilesOnHDFSToLocalFile.fieldnames())
            first_line = next(reader)
            # Use batch insertion helper:
            execute_values(
                cur,
                # UPSERT so additional data for existing records is retained:
                """UPSERT INTO crawl_files (filename, job_name, job_launch, full_path, extension, size, type, created_at, last_seen_at) VALUES %s""",
                self.entry_generator(reader),
                page_size=1000
            )

        # FIXME also check last_seen_at date and warn if anything appears to have gone missing?

        # And shut down:
        cur.close()
        conn.close()

        # Sanity check:
        if self.total == 0:
            raise Exception("No filenames generated! Something went wrong!")

        # Record we completed successfully:
        self.output().touch()


class ListWarcFileSets(luigi.Task):
    """
    Lists the WARCS and arranges them by date:
    """
    date = luigi.DateParameter(default=datetime.date.today())
    stream = luigi.EnumParameter(enum=CrawlStream, default=CrawlStream.frequent)
    task_namespace = 'access.report'

    def requires(self):
        return DownloadHDFSFileList(self.date, self.stream)

    #def complete(self):
    #    return False

    def output(self):
        return state_file(self.date, 'warc', '%s-warc-filesets.txt' % self.stream.name)

    def run(self):
        # Go through the data and assemble the resources for each crawl:
        filenames = []
        with self.input().open('r') as fin:
            reader = csv.DictReader(fin, fieldnames=ListAllFilesOnHDFSToLocalFile.fieldnames())
            first_line = reader.next()
            for item in reader:
                # Parse file paths and names:
                p = HdfsPathParser(item)
                # Look at WARCS in this stream:
                if p.stream == self.stream and p.kind == 'warcs' and p.file_name.endswith(".warc.gz"):
                    filenames.append(p.file_path)

        # Sanity check:
        if len(filenames) == 0:
            raise Exception("No filenames generated! Something went wrong!")

        # Finally, emit the list of output files as the task output:
        filenames = sorted(filenames)
        counter = 0
        with self.output().open('w') as f:
            for output_path in filenames:
                if counter > 0:
                    if counter % 10000 == 0:
                        f.write('\n')
                    else:
                        f.write(' ')
                f.write('%s' % output_path)
                counter += 1


class ListWarcsByDate(luigi.Task):
    """
    Lists the WARCS with datestamps corresponding to a particular day. Defaults to yesterday.
    """
    date = luigi.DateParameter(default=datetime.date.today())
    stream = luigi.EnumParameter(enum=CrawlStream, default=CrawlStream.frequent)

    task_namespace = 'access.report'

    file_count = 0

    def requires(self):
        # Get todays list:
        return DownloadHDFSFileList(self.date)

    def output(self):
        return state_file(self.date, 'warcs', '%s-warc-files-by-date.txt' % self.stream.name )

    def run(self):
        # Build up a list of all WARCS, by day:
        by_day = {}
        with self.input().open('r') as fin:
            reader = csv.DictReader(fin, fieldnames=ListAllFilesOnHDFSToLocalFile.fieldnames())
            first_line = reader.next()
            for item in reader:
                # Parse file paths and names:
                p = HdfsPathParser(item)
                # Look at WARCS in this stream:
                if p.stream == self.stream and p.kind == 'warcs':
                    # Take the first ten characters of the timestamp - YYYY-MM-DD:
                    file_datestamp = p.timestamp[0:10]

                    if file_datestamp not in by_day:
                        by_day[file_datestamp] = []

                    by_day[file_datestamp].append(item)
        # Write them out:
        filenames = []
        for datestamp in by_day:
            datestamp_output = state_file(None, 'warcs-by-day', '%s-%s-%s-warcs-for-date.txt' % (self.stream.name,datestamp,len(by_day[datestamp])))
            with datestamp_output.open('w') as f:
                f.write(json.dumps(by_day[datestamp], indent=2))

        # Emit the list of output files as the task output:
        self.file_count = len(filenames)
        with self.output().open('w') as f:
            for output_path in filenames:
                f.write('%s\n' % output_path)


class ListWarcsForDate(luigi.Task):
    """
    Lists the WARCS with datestamps corresponding to a particular day. Defaults to yesterday.
    """
    target_date = luigi.DateParameter(default=datetime.date.today() - datetime.timedelta(1))
    stream = luigi.EnumParameter(enum=CrawlStream, default=CrawlStream.frequent)
    date = luigi.DateParameter(default=datetime.date.today())

    task_namespace = 'access.report'

    def requires(self):
        # Get current list (use self.date not the target_date):
        return ListWarcsByDate(self.date, self.stream)

    def find_best_path(self):
        # List all the warcs-by-date files and select the one with the highest count.
        datestamp = self.target_date.strftime("%Y-%m-%d")
        target_path = state_file(None, 'warcs-by-day', '%s-%s-*-warcs-for-date.txt' % (self.stream.name, datestamp)).path
        max_count = 0
        best_path = None
        for path in glob.glob(target_path):
            count = int(re.search('-([0-9]+)-warcs-for-date.txt$', path).group(1))
            # If this has a higher file count, use it:
            if count > max_count:
                max_count = count
                best_path = path

        return best_path

    def complete(self):
        # Ensure ListWarcsByDate has been run:
        if not self.requires().complete():
            return False
        # If the pre-requisite has definately run, proceed as normal:
        return super(ListWarcsForDate, self).complete()

    def output(self):
        best_path = self.find_best_path()
        if best_path:
            # List of WARCs for the given day stored here:
            return luigi.LocalTarget(path=best_path)
        else:
            # Return special Target that says no WARCs were to be found
            return NoWARCsToday()

    def run(self):
        # The output does all the work here.
        pass


class NoWARCsToday(luigi.Target):
    """
    Special Target that exists only to inform downstream tasks that there are no WARCs for a given day.
    """
    def exists(self):
        return True


if __name__ == '__main__':
    import logging

    logging.getLogger().setLevel(logging.INFO)
    luigi.interface.setup_interface_logging()

    class Color(enum.Enum):
        RED = 1
        GREEN = 2
        BLUE = 3

    print(Color.RED)

    v = CrawlStream.frequent
    print(v)
    print(v.name)
