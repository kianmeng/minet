# =============================================================================
# Minet Scrape CLI Action
# =============================================================================
#
# Logic of the scrape action.
#
import csv
import sys
import ndjson
import casanova
from termcolor import colored
from collections import namedtuple
from os.path import basename
from multiprocessing import Pool

from minet import Scraper
from minet.exceptions import (
    DefinitionInvalidFormatError,
)
from minet.scrape.exceptions import (
    InvalidScraperError,
    CSSSelectorTooComplex,
    ScraperEvalError,
    ScraperEvalTypeError,
    ScraperEvalNoneError
)
from minet.scrape.analysis import report_validation_errors
from minet.cli.utils import (
    open_output_file,
    die,
    create_glob_iterator,
    create_report_iterator,
    LazyLineDict,
    LoadingBar,
    read_potentially_gzipped_path
)

ScrapeWorkerResult = namedtuple(
    'ScrapeWorkerResult',
    ['error', 'items']
)

PROCESS_SCRAPER = None


def init_process(definition, strain):
    global PROCESS_SCRAPER

    PROCESS_SCRAPER = Scraper(definition, strain=strain)


def worker(payload):
    row, headers, path, encoding, content, args = payload
    output_format, plural_separator = args

    # Reading from file
    if content is None:
        try:
            content = read_potentially_gzipped_path(path, encoding=encoding)
        except (FileNotFoundError, UnicodeDecodeError) as e:
            return ScrapeWorkerResult(e, None)

    # Building context
    context = {}

    if row:
        context['line'] = LazyLineDict(headers, row)

    if path:
        context['path'] = path
        context['basename'] = basename(path)

    # Attempting to scrape
    if output_format == 'csv':
        items = PROCESS_SCRAPER.as_csv_dict_rows(content, context=context, plural_separator=plural_separator)
    else:
        items = PROCESS_SCRAPER.as_records(content, context=context)

    # NOTE: errors will only be raised when we consume the generators created above
    try:
        items = list(items)
    except (ScraperEvalError, ScraperEvalTypeError, ScraperEvalNoneError) as error:
        return ScrapeWorkerResult(error, None)

    return ScrapeWorkerResult(None, items)


def scrape_action(namespace):

    output_file = open_output_file(namespace.output)

    # Parsing scraper definition
    try:
        scraper = Scraper(namespace.scraper, strain=namespace.strain)
    except DefinitionInvalidFormatError:
        die([
            'Unknown scraper format!',
            'It should be a JSON or YAML file.'
        ])
    except FileNotFoundError:
        die('Could not find scraper file!')
    except InvalidScraperError as error:
        print('Your scraper is invalid! Check the following errors:', file=sys.stderr)
        print(file=sys.stderr)
        sys.stderr.write(report_validation_errors(error.validation_errors))
        die()
    except CSSSelectorTooComplex:
        die([
            'Your strainer\'s CSS selector %s is too complex.' % colored(namespace.strain, 'blue'),
            'You cannot use relations to create a strainer.',
            'Try to simplify the selector you passed to --strain.'
        ])

    if namespace.validate:
        print('You scraper is valid.', file=sys.stderr)
        sys.exit(0)

    if scraper.headers is None and namespace.format == 'csv':
        die([
            'Your scraper does not yield tabular data.',
            'Try changing it or setting --format to "jsonl".'
        ])

    loading_bar = LoadingBar(
        desc='Scraping pages',
        total=namespace.total,
        unit='page',
        stats={'p': namespace.processes},
        delay=0.5
    )

    proc_args = (
        namespace.format,
        namespace.separator
    )

    if namespace.glob is not None:
        files = create_glob_iterator(namespace, proc_args)
    else:
        reader = casanova.reader(namespace.report)

        try:
            files = create_report_iterator(namespace, reader, proc_args, loading_bar)
        except NotADirectoryError:
            loading_bar.die([
                'Could not find the "%s" directory!' % namespace.input_dir,
                'Did you forget to specify it with -i/--input-dir?'
            ])

    if namespace.format == 'csv':
        output_writer = csv.DictWriter(output_file, fieldnames=scraper.headers)
        output_writer.writeheader()
    else:
        output_writer = ndjson.writer(output_file)

    pool = Pool(
        namespace.processes,
        initializer=init_process,
        initargs=(scraper.definition, namespace.strain)
    )

    with pool:
        for error, items in pool.imap_unordered(worker, files):
            loading_bar.update()

            if error is not None:
                loading_bar.inc('errors')
                continue

            for item in items:
                output_writer.writerow(item)

    loading_bar.close()
    output_file.close()
