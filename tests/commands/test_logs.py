from click.testing import CliRunner
from pytest_mock import MockFixture

from opta.commands.logs import logs
from opta.layer import Layer
from opta.module import Module


def test_logs(mocker: MockFixture) -> None:
    mocked_layer_class = mocker.patch("opta.commands.logs.Layer")
    mocked_layer = mocker.Mock(spec=Layer)
    mocked_layer.name = "layer_name"
    mocked_layer.cloud = "aws"
    mocked_layer_class.load_from_yaml.return_value = mocked_layer
    layer_gen_all = mocker.patch("opta.commands.logs.gen_all")
    configure_kubectl = mocker.patch("opta.commands.logs.configure_kubectl")
    load_kube_config = mocker.patch("opta.commands.logs.load_kube_config")

    mocked_module = mocker.Mock(spec=Module)
    mocked_module.type = "k8s-service"
    mocked_module.name = "module_name"
    mocked_layer.get_module_by_type.return_value = [mocked_module]

    mocked_tail_module_log = mocker.patch("opta.commands.logs.tail_module_log")

    runner = CliRunner()
    result = runner.invoke(logs)

    assert result.exit_code == 0
    layer_gen_all.assert_called_once_with(mocked_layer)
    configure_kubectl.assert_called_once_with(mocked_layer)
    load_kube_config.assert_called_once()

    mocked_tail_module_log.assert_called_once_with(mocked_layer, "module_name", None)
    mocked_layer.get_module_by_type.assert_called_once_with("k8s-service")
