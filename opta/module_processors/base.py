from typing import TYPE_CHECKING, Dict, Optional, Tuple

from opta.exceptions import UserErrors

if TYPE_CHECKING:
    from opta.layer import Layer
    from opta.module import Module


class ModuleProcessor:
    def __init__(self, module: "Module", layer: "Layer") -> None:
        self.layer = layer
        self.module = module

    def process(self, module_idx: int) -> None:
        if self.module.data.get("root_only", False) and self.layer.parent is not None:
            raise UserErrors(
                f"Module {self.module.name} can only specified in a root layer"
            )
        self.module.data["env_name"] = self.layer.get_env()
        self.module.data["layer_name"] = self.layer.name
        self.module.data["module_name"] = self.module.name

    def post_hook(self, module_idx: int, exception: Optional[Exception]) -> None:
        pass


class AWSK8sModuleProcessor(ModuleProcessor):
    def __init__(self, module: "Module", layer: "Layer"):
        super(AWSK8sModuleProcessor, self).__init__(module, layer)

    def process(self, module_idx: int) -> None:
        eks_module_refs = get_eks_module_refs(self.layer, module_idx)
        self.module.data["openid_provider_url"] = eks_module_refs[0]
        self.module.data["openid_provider_arn"] = eks_module_refs[1]
        self.module.data["eks_cluster_name"] = eks_module_refs[2]
        super(AWSK8sModuleProcessor, self).process(module_idx)


class GcpK8sModuleProcessor(ModuleProcessor):
    def __init__(self, module: "Module", layer: "Layer"):
        super(GcpK8sModuleProcessor, self).__init__(module, layer)

    def process(self, module_idx: int) -> None:
        super(GcpK8sModuleProcessor, self).process(module_idx)


def get_eks_module_refs(layer: "Layer", module_idx: int) -> Tuple[str, str, str]:
    from_parent = False
    eks_modules = layer.get_module_by_type("aws-eks", module_idx)
    if len(eks_modules) == 0 and layer.parent is not None:
        from_parent = True
        eks_modules = layer.parent.get_module_by_type("aws-eks")

    if len(eks_modules) == 0:
        raise UserErrors(
            "Did not find the aws-eks module in the layer or the parent layer"
        )
    eks_module = eks_modules[0]
    module_source = (
        "data.terraform_remote_state.parent.outputs"
        if from_parent
        else f"module.{eks_module.name}"
    )
    return (
        f"${{{{{module_source}.k8s_openid_provider_url}}}}",
        f"${{{{{module_source}.k8s_openid_provider_arn}}}}",
        f"${{{{{module_source}.k8s_cluster_name}}}}",
    )


def get_aws_base_module_refs(layer: "Layer") -> Dict[str, str]:
    from_parent = False
    aws_base_modules = layer.get_module_by_type("aws-base")
    if len(aws_base_modules) == 0 and layer.parent is not None:
        from_parent = True
        aws_base_modules = layer.parent.get_module_by_type("aws-base")

    if len(aws_base_modules) == 0:
        raise UserErrors(
            "Did not find the aws-base module in the layer or the parent layer"
        )
    aws_base_module = aws_base_modules[0]
    module_source = (
        "data.terraform_remote_state.parent.outputs"
        if from_parent
        else f"module.{aws_base_module.name}"
    )
    return {
        "kms_account_key_arn": f"${{{{{module_source}.kms_account_key_arn}}}}",
        "kms_account_key_id": f"${{{{{module_source}.kms_account_key_id}}}}",
        "vpc_id": f"${{{{{module_source}.vpc_id}}}}",
        "private_subnet_ids": f"${{{{{module_source}.private_subnet_ids}}}}",
        "public_subnets_ids": f"${{{{{module_source}.public_subnets_ids}}}}",
    }
