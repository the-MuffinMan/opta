from __future__ import annotations

import os
import re
import shutil
import tempfile
from os import path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

import git
import yaml

from opta.constants import REGISTRY
from opta.core.validator import validate_yaml
from opta.exceptions import UserErrors
from opta.module import Module
from opta.module_processors.aws_dns import AwsDnsProcessor
from opta.module_processors.aws_eks import AwsEksProcessor
from opta.module_processors.aws_email import AwsEmailProcessor
from opta.module_processors.aws_iam_role import AwsIamRoleProcessor
from opta.module_processors.aws_iam_user import AwsIamUserProcessor
from opta.module_processors.aws_k8s_base import AwsK8sBaseProcessor
from opta.module_processors.aws_k8s_service import AwsK8sServiceProcessor
from opta.module_processors.aws_sns import AwsSnsProcessor
from opta.module_processors.aws_sqs import AwsSqsProcessor
from opta.module_processors.base import ModuleProcessor
from opta.module_processors.datadog import DatadogProcessor
from opta.module_processors.gcp_gke import GcpGkeProcessor
from opta.module_processors.gcp_k8s_base import GcpK8sBaseProcessor
from opta.module_processors.gcp_k8s_service import GcpK8sServiceProcessor
from opta.module_processors.helm_chart import HelmChartProcessor
from opta.module_processors.runx import RunxProcessor
from opta.plugins.derived_providers import DerivedProviders
from opta.utils import deep_merge, hydrate, logger

AWS_PROVIDER_VERSION = "3.38.0"
GCP_PROVIDER_VERSION = "3.66.1"


class Layer:
    def __init__(
        self,
        name: str,
        org_name: Optional[str],
        providers: Dict[Any, Any],
        modules_data: List[Any],
        parent: Optional[Layer] = None,
        variables: Optional[Dict[str, Any]] = None,
        original_spec: str = "",
    ):
        if not Layer.valid_name(name):
            raise UserErrors(
                "Invalid layer, can only contain letters, dashes and numbers!"
            )
        self.name = name
        self.original_spec = original_spec
        self.parent = parent
        if parent is None and org_name is None:
            raise UserErrors("Config must have org name or a parent who has an org name")
        self.org_name = org_name
        if self.parent and self.org_name is None:
            self.org_name = self.parent.org_name
        self.providers = providers
        total_base_providers = deep_merge(
            self.providers, self.parent.providers if self.parent else {}
        )
        self.cloud: str
        if "google" in total_base_providers and "aws" in total_base_providers:
            raise UserErrors(
                "You can have AWS as the cloud provider, or google, but not both"
            )
        if "google" in total_base_providers:
            self.cloud = "google"
        elif "aws" in total_base_providers:
            self.cloud = "aws"
        else:
            raise UserErrors("No cloud provider (AWS or GCP) found")
        self.variables = variables or {}
        self.modules = []
        for module_data in modules_data:
            self.modules.append(Module(self, module_data, self.parent,))
        module_names: set = set()
        for module in self.modules:
            if module.name in module_names:
                raise UserErrors(
                    f"The module name {module.name} is used multiple time in the "
                    "layer. Module names must be unique per layer"
                )

    @classmethod
    def load_from_yaml(cls, config: str, env: Optional[str]) -> Layer:
        t = None
        if config.startswith("git@"):
            logger.debug("Loading layer from git...")
            git_url, file_path = config.split("//")
            branch = "main"
            if "?" in file_path:
                file_path, file_vars = file_path.split("?")
                res = dict(
                    map(
                        lambda x: (x.split("=")[0], x.split("=")[1]), file_vars.split(",")
                    )
                )
                branch = res.get("ref", branch)
            t = tempfile.mkdtemp()
            # Clone into temporary dir
            git.Repo.clone_from(git_url, t, branch=branch, depth=1)
            config_path = os.path.join(t, file_path)
            with open(config_path) as f:
                config_string = f.read()
            conf = yaml.load(config_string, Loader=yaml.Loader)
        elif path.exists(config):
            config_path = config
            logger.debug(f"Loaded the following configfile:\n{open(config_path).read()}")
            with open(config_path) as f:
                config_string = f.read()
            conf = yaml.load(config_string, Loader=yaml.Loader)
        else:
            raise UserErrors(f"File {config} not found")

        conf["original_spec"] = config_string
        conf["path"] = config

        layer = cls.load_from_dict(conf, env)
        validate_yaml(config_path, layer.cloud)
        if t is not None:
            shutil.rmtree(t)
        return layer

    @classmethod
    def load_from_dict(cls, conf: Dict[Any, Any], env: Optional[str]) -> Layer:
        modules_data = conf.get("modules", [])
        environments = conf.pop("environments", None)
        original_spec = conf.pop("original_spec", "")
        name = conf.pop("name", None)
        if name is None:
            raise UserErrors("Config must have name")
        org_name = conf.pop("org_name", None)
        providers = conf.pop("providers", {})
        if "aws" in providers:
            providers["aws"]["version"] = AWS_PROVIDER_VERSION
        if "google" in providers:
            providers["google"]["version"] = GCP_PROVIDER_VERSION
        if environments:
            potential_envs: Dict[str, Tuple] = {}
            for env_meta in environments:
                env_name = env_meta["name"]
                parent_path: str = env_meta["path"]
                if not parent_path.startswith("git@") and not parent_path.startswith("/"):
                    parent_path = os.path.join(
                        os.path.dirname(conf["path"]), env_meta["path"]
                    )
                current_parent = cls.load_from_yaml(parent_path, None)
                if current_parent.parent is not None:
                    raise UserErrors(
                        "A parent can not have a parent, only one level of parent-child allowed."
                    )
                current_env = current_parent.get_env()
                if current_env in potential_envs.keys():
                    raise UserErrors(
                        f"Same environment: {current_env} is imported twice as parent"
                    )
                potential_envs[env_name] = (current_parent, env_meta)

            if len(potential_envs) > 1 and env not in potential_envs:
                raise UserErrors(
                    f"Invalid --env flag, valid ones are {list(potential_envs.keys())}"
                )
            if env is None:
                current_parent, env_meta = list(potential_envs.values())[0]
            else:
                current_parent, env_meta = potential_envs[env]
            current_variables = env_meta.get("variables", {})
            current_variables = deep_merge(current_variables, env_meta.get("vars", {}))
            return cls(
                name,
                org_name,
                providers,
                modules_data,
                current_parent,
                current_variables,
                original_spec,
            )
        return cls(name, org_name, providers, modules_data, original_spec=original_spec)

    @staticmethod
    def valid_name(name: str) -> bool:
        pattern = "^[A-Za-z0-9-]*$"
        return bool(re.match(pattern, name))

    def get_env(self) -> str:
        if self.parent is not None:
            return self.parent.get_env()
        return self.name

    def get_module(
        self, module_name: str, module_idx: Optional[int] = None
    ) -> Optional[Module]:
        module_idx = module_idx or len(self.modules) - 1
        for module in self.modules[0 : module_idx + 1]:
            if module.name == module_name:
                return module
        return None

    def get_module_by_type(
        self, module_type: str, module_idx: Optional[int] = None
    ) -> list[Module]:
        module_idx = module_idx or len(self.modules) - 1
        modules = []
        for module in self.modules[0 : module_idx + 1]:
            if module.type == module_type or module.aliased_type == module_type:
                modules.append(module)
        return modules

    def outputs(self, module_idx: Optional[int] = None) -> Iterable[str]:
        ret: List[str] = []
        module_idx = module_idx or len(self.modules) - 1
        for module in self.modules[0 : module_idx + 1]:
            ret += module.outputs()
        return ret

    def gen_tf(self, module_idx: int) -> Dict[Any, Any]:
        ret: Dict[Any, Any] = {}
        for module in self.modules[0 : module_idx + 1]:
            module_type = module.aliased_type or module.type
            if module_type == "aws-k8s-service":
                AwsK8sServiceProcessor(module, self).process(module_idx)
            elif module_type == "aws-k8s-base":
                AwsK8sBaseProcessor(module, self).process(module_idx)
            elif module_type == "datadog":
                DatadogProcessor(module, self).process(module_idx)
            elif module_type == "gcp-k8s-base":
                GcpK8sBaseProcessor(module, self).process(module_idx)
            elif module_type == "gcp-k8s-service":
                GcpK8sServiceProcessor(module, self).process(module_idx)
            elif module_type == "gcp-gke":
                GcpGkeProcessor(module, self).process(module_idx)
            elif module_type == "aws-dns":
                AwsDnsProcessor(module, self).process(module_idx)
            elif module_type == "runx":
                RunxProcessor(module, self).process(module_idx)
            elif module_type == "helm-chart":
                HelmChartProcessor(module, self).process(module_idx)
            elif module_type == "aws-iam-role":
                AwsIamRoleProcessor(module, self).process(module_idx)
            elif module_type == "aws-iam-user":
                AwsIamUserProcessor(module, self).process(module_idx)
            elif module_type == "aws-eks":
                AwsEksProcessor(module, self).process(module_idx)
            elif module_type == "aws-ses":
                AwsEmailProcessor(module, self).process(module_idx)
            elif module_type == "aws-sqs":
                AwsSqsProcessor(module, self).process(module_idx)
            elif module_type == "aws-sns":
                AwsSnsProcessor(module, self).process(module_idx)
            else:
                ModuleProcessor(module, self).process(module_idx)
        if self.parent is not None and self.parent.get_module("runx") is not None:
            RunxProcessor(self.parent.get_module("runx"), self).process(  # type:ignore
                module_idx
            )
        previous_module_reference = None
        for module in self.modules[0 : module_idx + 1]:
            output_prefix = (
                None if len(self.get_module_by_type(module.type)) == 1 else module.name
            )
            ret = deep_merge(
                module.gen_tf(
                    depends_on=previous_module_reference, output_prefix=output_prefix
                ),
                ret,
            )
            if module.desc.get("halt"):
                previous_module_reference = [f"module.{module.name}"]

        return hydrate(ret, self.metadata_hydration())

    def post_hook(self, module_idx: int, exception: Optional[Exception]) -> None:
        for module in self.modules[0 : module_idx + 1]:
            module_type = module.data["type"]
            if module_type == "aws-k8s-service":
                AwsK8sServiceProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-k8s-base":
                AwsK8sBaseProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "datadog":
                DatadogProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "gcp-k8s-base":
                GcpK8sBaseProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "gcp-k8s-service":
                GcpK8sServiceProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "gcp-gke":
                GcpGkeProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-dns":
                AwsDnsProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "runx":
                RunxProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "helm-chart":
                HelmChartProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-iam-role":
                AwsIamRoleProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-iam-user":
                AwsIamUserProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-eks":
                AwsEksProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-ses":
                AwsEmailProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-sqs":
                AwsSqsProcessor(module, self).post_hook(module_idx, exception)
            elif module_type == "aws-sns":
                AwsSnsProcessor(module, self).post_hook(module_idx, exception)
            else:
                ModuleProcessor(module, self).post_hook(module_idx, exception)
        if self.parent is not None and self.parent.get_module("runx") is not None:
            RunxProcessor(self.parent.get_module("runx"), self).post_hook(  # type:ignore
                module_idx, exception
            )

    def metadata_hydration(self) -> Dict[Any, Any]:
        parent_name = self.parent.name if self.parent is not None else "nil"
        parent = None
        if self.parent is not None:
            parent = SimpleNamespace(
                **{
                    k: f"${{data.terraform_remote_state.parent.outputs.{k}}}"
                    for k in self.parent.outputs()
                }
            )
        return {
            "parent": parent,
            "vars": SimpleNamespace(**self.variables),
            "variables": SimpleNamespace(**self.variables),
            "parent_name": parent_name,
            "layer_name": self.name,
            "state_storage": self.state_storage(),
            "env": self.get_env(),
        }

    def state_storage(self) -> str:
        if self.parent is not None:
            return self.parent.state_storage()
        else:
            return f"opta-tf-state-{self.org_name}-{self.name}"

    def gen_providers(self, module_idx: int) -> Dict[Any, Any]:
        ret: Dict[Any, Any] = {"provider": {}}
        providers = self.providers
        if self.parent is not None:
            providers = deep_merge(providers, self.parent.providers)
        for k, v in providers.items():
            self.handle_special_providers(k, v)
            ret["provider"][k] = v
            if k in REGISTRY["backends"]:
                hydration = deep_merge(self.metadata_hydration(), {"provider": v})
                ret["terraform"] = hydrate(
                    REGISTRY["backends"][k]["terraform"], hydration
                )

                if self.parent is not None:
                    # Add remote state
                    backend, config = list(
                        REGISTRY["backends"][k]["terraform"]["backend"].items()
                    )[0]
                    ret["data"] = {
                        "terraform_remote_state": {
                            "parent": {
                                "backend": backend,
                                "config": hydrate(
                                    config,
                                    {
                                        "layer_name": self.parent.name,
                                        "state_storage": self.state_storage(),
                                        "provider": self.parent.providers.get(k, {}),
                                    },
                                ),
                            }
                        }
                    }

        # Add derived providers like k8s from parent
        ret = deep_merge(ret, DerivedProviders(self.parent, is_parent=True).gen_tf())
        # Add derived providers like k8s from own modules
        ret = deep_merge(
            ret, DerivedProviders(self, is_parent=False).gen_tf(module_idx=module_idx)
        )

        return ret

    # Special logic for mapping the opta config to the provider block
    def handle_special_providers(self, provider_name: str, provider_data: dict) -> None:
        # Terraform requires an array of AWS account ids, but having the customer specify
        # that is awk, so transform it during the mapping.
        if provider_name == "aws" and "account_id" in provider_data:
            aws_account_id = provider_data.pop("account_id")
            if str(aws_account_id) not in (
                self.original_spec
                + ("" if self.parent is None else self.parent.original_spec)
            ):
                raise UserErrors(
                    "The AWS account id which opta parsed is different than the one in the original yaml. "
                    "Odds are this is because the account starts with a leading 0, which we'll fix soon."
                )
            provider_data["allowed_account_ids"] = [aws_account_id]

    # Get the root-most layer
    def root(self) -> "Layer":
        layer = self
        while layer.parent is not None:
            layer = layer.parent

        return layer
