from typing import Any

from click.testing import CliRunner, Result
from pytest import fixture
from pytest_mock import MockFixture

from opta.commands.apply import apply
from opta.constants import TF_PLAN_PATH
from opta.core.kubernetes import tail_module_log, tail_namespace_events
from opta.layer import Layer
from opta.module import Module


@fixture
def basic_mocks(mocker: MockFixture) -> None:
    mocker.patch("opta.commands.apply.is_tool", return_value=True)
    mocker.patch("opta.commands.apply.amplitude_client.send_event")
    mocker.patch("opta.commands.apply.gen_opta_resource_tags")

    # Mock remote state
    mocker.patch(
        "opta.commands.apply.Terraform.get_existing_modules",
        return_value={"deletedmodule"},
    )

    # Mock opta config
    mocked_layer = mocker.Mock()
    mocked_layer.name = "test"
    mocked_layer.cloud = "aws"
    fake_module = Module(mocked_layer, data={"type": "k8s-service", "name": "fakemodule"})
    mocker.patch("opta.commands.apply.gen", return_value=iter([(0, [fake_module], 1)]))
    mocker.patch("opta.commands.apply.AWS")


@fixture
def mocked_layer(mocker: MockFixture) -> Any:
    mocked_layer_class = mocker.patch("opta.commands.apply.Layer")
    mocked_layer = mocker.Mock(spec=Layer)
    mocked_layer.variables = {}
    mocked_layer.name = "blah"
    mocked_layer.cloud = "aws"
    mocked_layer.gen_providers = lambda x: {"provider": {"aws": {"region": "us-east-1"}}}
    mocked_layer_class.load_from_yaml.return_value = mocked_layer

    return mocked_layer


def test_apply(mocker: MockFixture, mocked_layer: Any, basic_mocks: Any) -> None:
    mocked_click = mocker.patch("opta.commands.apply.click")
    mocker.patch("opta.commands.apply.configure_kubectl")
    mocker.patch(
        "opta.commands.apply._fetch_availability_zones", return_value=["a", "b", "c"]
    )
    mocker.patch("opta.commands.apply.Terraform.downloaded_state")
    mocker.patch("opta.commands.apply.get_cluster_name")
    mocker.patch("opta.commands.apply.Terraform.download_state")
    tf_apply = mocker.patch("opta.commands.apply.Terraform.apply")
    tf_plan = mocker.patch("opta.commands.apply.Terraform.plan")
    tf_show = mocker.patch("opta.commands.apply.Terraform.show")
    tf_create_storage = mocker.patch("opta.commands.apply.Terraform.create_state_storage")
    mocked_thread = mocker.patch("opta.commands.apply.Thread")
    mocked_layer.get_module_by_type.return_value = [mocker.Mock()]

    # Terraform apply should be called with the configured module (fake_module) and the remote state
    # module (deleted_module) as targets.
    runner = CliRunner()
    result = runner.invoke(apply)
    assert result.exit_code == 0
    tf_apply.assert_called_once_with(
        mocked_layer, TF_PLAN_PATH, no_init=True, quiet=False
    )
    tf_plan.assert_called_once_with(
        "-lock=false",
        "-input=false",
        f"-out={TF_PLAN_PATH}",
        "-target=module.deletedmodule",
        "-target=module.fakemodule",
        quiet=True,
    )
    mocked_click.confirm.assert_called_once_with(
        "The above are the planned changes for your opta run. Do you approve?",
        abort=True,
    )
    tf_show.assert_called_once_with(TF_PLAN_PATH)
    mocked_layer.get_module_by_type.assert_called_once_with("k8s-service", 0)
    tf_create_storage.assert_called_once_with(mocked_layer)
    mocked_thread.assert_has_calls(
        [
            mocker.call(
                target=tail_module_log,
                args=(mocked_layer, mocker.ANY, 10, 2),
                daemon=True,
            ),
            mocker.call().start(),
            mocker.call(
                target=tail_namespace_events, args=(mocked_layer, 0, 1), daemon=True,
            ),
            mocker.call().start(),
        ]
    )


def test_auto_approve(mocker: MockFixture, mocked_layer: Any, basic_mocks: Any) -> None:
    mocked_click = mocker.patch("opta.commands.apply.click")
    mocker.patch("opta.commands.apply.configure_kubectl")
    mocker.patch(
        "opta.commands.apply._fetch_availability_zones", return_value=["a", "b", "c"]
    )
    mocker.patch("opta.commands.apply.Terraform.downloaded_state")
    mocker.patch("opta.commands.apply.Terraform.download_state")
    mocker.patch("opta.commands.apply.get_cluster_name")
    tf_apply = mocker.patch("opta.commands.apply.Terraform.apply")
    tf_plan = mocker.patch("opta.commands.apply.Terraform.plan")
    tf_show = mocker.patch("opta.commands.apply.Terraform.show")
    tf_create_storage = mocker.patch("opta.commands.apply.Terraform.create_state_storage")
    mocked_thread = mocker.patch("opta.commands.apply.Thread")
    mocked_layer.get_module_by_type.return_value = [mocker.Mock()]

    # Terraform apply should be called with the configured module (fake_module) and the remote state
    # module (deleted_module) as targets.
    runner = CliRunner()
    result: Result = runner.invoke(apply, "--auto-approve")
    assert result.exit_code == 0
    tf_apply.assert_called_once_with(
        mocked_layer, "-auto-approve", TF_PLAN_PATH, no_init=True, quiet=False
    )
    tf_plan.assert_called_once_with(
        "-lock=false",
        "-input=false",
        f"-out={TF_PLAN_PATH}",
        "-target=module.deletedmodule",
        "-target=module.fakemodule",
        quiet=True,
    )
    mocked_click.confirm.assert_not_called()
    tf_show.assert_called_once_with(TF_PLAN_PATH)
    mocked_layer.get_module_by_type.assert_called_once_with("k8s-service", 0)
    tf_create_storage.assert_called_once_with(mocked_layer)
    mocked_thread.assert_has_calls(
        [
            mocker.call(
                target=tail_module_log,
                args=(mocked_layer, mocker.ANY, 10, 2),
                daemon=True,
            ),
            mocker.call().start(),
            mocker.call(
                target=tail_namespace_events, args=(mocked_layer, 0, 1), daemon=True,
            ),
            mocker.call().start(),
        ]
    )


def test_fail_on_2_azs(mocker: MockFixture, mocked_layer: Any) -> None:
    # Opta needs a region with at least 3 AZs, fewer should fail.
    mocker.patch(
        "opta.commands.apply._fetch_availability_zones",
        return_value=["us-west-1a", "us-west-1c"],
    )
    runner = CliRunner()
    result = runner.invoke(apply)
    assert "Opta requires a region with at least *3* availability zones." in str(
        result.exception
    )
