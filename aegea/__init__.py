"""
Amazon Web Services Operator Interface

For general help, run ``aegea help`` or visit https://github.com/kislyuk/aegea/wiki.
For help with individual commands, run ``aegea <command> --help``.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import os, sys, argparse, logging, shutil, json, datetime, traceback, errno, warnings
from textwrap import fill
import tweak
from botocore.exceptions import NoRegionError
from io import open

try:
    import pkg_resources
    __version__ = pkg_resources.get_distribution(__name__).version
except Exception:
    __version__ = "0.0.0"

if sys.version_info < (2, 7, 9): # See https://urllib3.readthedocs.io/en/latest/advanced-usage.html#sni-warning
    try:
        import botocore.vendored.requests.packages.urllib3.contrib.pyopenssl as p
        p.inject_into_urllib3()
        import requests.packages.urllib3.contrib.pyopenssl as p
        p.inject_into_urllib3()
    except ImportError:
        msg = 'Your Python version is too old to support TLS SNI. Run "pip install pyopenssl ndg-httpsclient" to avoid connection issues.' # noqa
        warnings.warn(msg)

logger = logging.getLogger(__name__)

config, parser = None, None
_subparsers = {}

class AegeaConfig(tweak.Config):
    base_config_file = os.path.join(os.path.dirname(__file__), "base_config.yml")
    @property
    def config_files(self):
        return [self.base_config_file] + tweak.Config.config_files.fget(self)

    @property
    def user_config_dir(self):
        return os.path.join(self._user_config_home, self._name)

def initialize():
    global config, parser
    from .util.printing import BOLD, RED, ENDC
    config = AegeaConfig(__name__, use_yaml=True, save_on_exit=False)
    if not os.path.exists(config.config_files[2]):
        config_dir = os.path.dirname(os.path.abspath(config.config_files[2]))
        try:
            os.makedirs(config_dir)
        except OSError as e:
            if not (e.errno == errno.EEXIST and os.path.isdir(config_dir)):
                raise
        shutil.copy(os.path.join(os.path.dirname(__file__), "user_config.yml"), config.config_files[2])
        logger.info("Wrote new config file %s with default values", config.config_files[2])
        config = AegeaConfig(__name__, use_yaml=True, save_on_exit=False)

    parser = argparse.ArgumentParser(
        description="{}: {}".format(BOLD() + RED() + __name__.capitalize() + ENDC(), fill(__doc__.strip())),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--version", action="version", version="%(prog)s {version}".format(version=__version__))

    def help(args):
        parser.print_help()
    register_parser(help)

def main(args=None):
    parsed_args = parser.parse_args(args=args)
    has_attrs = (getattr(parsed_args, "sort_by", None) and
                 getattr(parsed_args, "columns", None))
    if has_attrs and parsed_args.sort_by not in parsed_args.columns:
        parsed_args.columns.append(parsed_args.sort_by)
    try:
        result = parsed_args.entry_point(parsed_args)
    except Exception as e:
        if isinstance(e, NoRegionError):
            msg = "The AWS CLI is not configured."
            msg += " Please configure it using instructions at"
            msg += " http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html"
            exit(msg)
        elif logger.level < logging.ERROR:
            raise
        else:
            err_msg = traceback.format_exc()
            try:
                err_log_filename = os.path.join(config.user_config_dir, "error.log")
                with open(err_log_filename, "ab") as fh:
                    print(datetime.datetime.now().isoformat(), file=fh)
                    print(err_msg, file=fh)
                exit("{}: {}. See {} for error details.".format(e.__class__.__name__, e, err_log_filename))
            except Exception:
                print(err_msg, file=sys.stderr)
                exit(os.EX_SOFTWARE)
    if isinstance(result, SystemExit):
        raise result
    elif result is not None:
        if isinstance(result, dict) and "ResponseMetadata" in result:
            del result["ResponseMetadata"]
        print(json.dumps(result, indent=2, default=lambda x: str(x)))

def register_parser(function, parent=None, name=None, **add_parser_args):
    if config is None:
        initialize()
    if parent is None:
        parent = parser
    if parent.prog not in _subparsers:
        _subparsers[parent.prog] = parent.add_subparsers()
    subparser = _subparsers[parent.prog].add_parser(name or function.__name__, **add_parser_args)
    subparser.add_argument("--max-col-width", "-w", type=int, default=32,
                           help="When printing tables, truncate column contents to this width. Set to 0 for auto fit.")
    subparser.add_argument("--json", action="store_true",
                           help="Output tabular data as a JSON-formatted list of objects")
    subparser.add_argument("--log-level", type=logger.setLevel,
                           help=str([logging.getLevelName(i) for i in range(0, 60, 10)]),
                           default=config.get("log_level"))
    subparser.set_defaults(entry_point=function)
    if parent and sys.version_info < (2, 7, 9): # See https://bugs.python.org/issue9351
        parent._defaults.pop("entry_point", None)
    command = subparser.prog[len(parser.prog)+1:].replace(" ", "_")
    subparser.set_defaults(**config.get(command, {}))
    if subparser.description is None:
        subparser.description = add_parser_args.get("help", function.__doc__)
    return subparser
