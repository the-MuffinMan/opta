from typing import Optional

import click
from kubernetes.config import load_kube_config

from opta.amplitude import amplitude_client
from opta.core.generator import gen_all
from opta.core.kubernetes import configure_kubectl, tail_namespace_events
from opta.layer import Layer


@click.command(hidden=True)
@click.option(
    "-e", "--env", default=None, help="The env to use when loading the config file"
)
@click.option(
    "-c", "--config", default="opta.yml", help="Opta config file", show_default=True
)
@click.option(
    "-s",
    "--seconds",
    default=None,
    help="Start showing logs from these many seconds in the past",
    show_default=False,
    type=int,
)
def events(env: Optional[str], config: str, seconds: Optional[int]) -> None:
    """Get stream of logs from your service"""

    # Configure kubectl
    layer = Layer.load_from_yaml(config, env)
    amplitude_client.send_event(amplitude_client.SHELL_EVENT)
    gen_all(layer)
    configure_kubectl(layer)
    load_kube_config()
    tail_namespace_events(layer, seconds)
