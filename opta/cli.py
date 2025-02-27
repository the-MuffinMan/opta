import os.path
import sys
from importlib.util import find_spec
from subprocess import CalledProcessError

import click
from click_didyoumean import DYMGroup

import opta.sentry  # noqa: F401 This leads to initialization of sentry sdk
from opta.amplitude import amplitude_client
from opta.cleanup_files import cleanup_files
from opta.commands.apply import apply
from opta.commands.deploy import deploy
from opta.commands.destroy import destroy
from opta.commands.events import events
from opta.commands.inspect_cmd import inspect
from opta.commands.kubectl import configure_kubectl
from opta.commands.logs import logs
from opta.commands.output import output
from opta.commands.push import push
from opta.commands.secret import secret
from opta.commands.shell import shell
from opta.commands.validate import validate
from opta.commands.version import version
from opta.exceptions import UserErrors
from opta.upgrade import check_version_upgrade
from opta.utils import dd_handler, dd_listener, logger


@click.group(cls=DYMGroup)
def cli() -> None:
    """Welcome to opta, runx's cli!"""
    pass


@cli.command(hidden=True)
def debugger() -> None:
    """The opta debugger -- to help you debug"""
    curses_spec = find_spec("_curses")
    curses_found = curses_spec is not None
    amplitude_client.send_event(amplitude_client.DEBUGGER_EVENT)

    if curses_found:
        from opta.debugger import Debugger

        dbg = Debugger()
        dbg.run()
    else:
        logger.warning(
            "We're very sorry but it seems like your python installation does not "
            "support curses for advanced cli ui experience. This is a known issue if you "
            "have pyenv + Big Sur-- pls look at this issue documentations: "
            "https://github.com/pyenv/pyenv/issues/1755"
        )


# Add commands
cli.add_command(apply)
cli.add_command(deploy)
cli.add_command(destroy)
cli.add_command(configure_kubectl)
cli.add_command(inspect)
cli.add_command(logs)
cli.add_command(output)
cli.add_command(push)
cli.add_command(secret)
cli.add_command(shell)
cli.add_command(validate)
cli.add_command(version)
cli.add_command(events)


if __name__ == "__main__":
    try:
        # In case OPTA_DEBUG is set, local state files may not be cleaned up
        # after the command.
        # However, we should still clean them up before the next command, or
        # else it may interfere with it.
        cleanup_files()
        cli()
    except CalledProcessError as e:
        logger.exception(e)
        if e.stderr is not None:
            logger.error(e.stderr.decode("utf-8"))
        sys.exit(1)
    except UserErrors as e:
        logger.error(e)
        sys.exit(1)
    except Exception as e:
        logger.exception(e)
        sys.exit(1)
    finally:
        # NOTE: Statements after the cli() invocation in the try clause are not executed.
        # A quick glance at click documentation did not show why that is the case or any workarounds.
        # Therefore adding this version check in the finally clause for now.
        check_version_upgrade()

        dd_listener.stop()
        dd_handler.flush()
        if os.environ.get("OPTA_DEBUG") is None:
            cleanup_files()
