from typing import TYPE_CHECKING, List

from opta.core.aws import AWS
from opta.exceptions import UserErrors
from opta.module_processors.base import AWSK8sModuleProcessor

if TYPE_CHECKING:
    from opta.layer import Layer
    from opta.module import Module


class AwsK8sServiceProcessor(AWSK8sModuleProcessor):
    def __init__(self, module: "Module", layer: "Layer"):
        if (module.aliased_type or module.type) != "aws-k8s-service":
            raise Exception(
                f"The module {module.name} was expected to be of type aws k8s service"
            )
        self.read_buckets: list[str] = []
        self.write_buckets: list[str] = []
        self.publish_queues: list[str] = []
        self.subscribe_queues: list[str] = []
        self.publish_topics: list[str] = []
        super(AwsK8sServiceProcessor, self).__init__(module, layer)

    def process(self, module_idx: int) -> None:
        # Update the secrets
        transformed_secrets = []
        if "original_secrets" in self.module.data:
            secrets = self.module.data["original_secrets"]
        else:
            secrets = self.module.data.get("secrets", [])
            self.module.data["original_secrets"] = secrets
        for secret in secrets:
            if type(secret) is str:
                transformed_secrets.append({"name": secret, "value": ""})
            else:
                raise Exception("Secret must be string or dict")
        self.module.data["secrets"] = transformed_secrets

        if isinstance(self.module.data.get("public_uri"), str):
            self.module.data["public_uri"] = [self.module.data["public_uri"]]

        # Handle links
        for link_data in self.module.data.get("links", []):
            if type(link_data) is str:
                target_module_name = link_data
                link_permissions = []
            elif type(link_data) is dict:
                target_module_name = list(link_data.keys())[0]
                link_permissions = list(link_data.values())[0]
            else:
                raise UserErrors(
                    f"Link data {link_data} must be a string or map holding the permissions"
                )
            module = self.layer.get_module(target_module_name, module_idx)
            if module is None:
                raise Exception(
                    f"Did not find the desired module {target_module_name} "
                    "make sure that the module you're referencing is listed before the k8s "
                    "app one"
                )
            module_type = module.aliased_type or module.type
            if module_type == "aws-postgres":
                self.handle_rds_link(module, link_permissions)
            elif module_type == "aws-redis":
                self.handle_redis_link(module, link_permissions)
            elif module_type == "aws-documentdb":
                self.handle_docdb_link(module, link_permissions)
            elif module_type == "aws-s3":
                self.handle_s3_link(module, link_permissions)
            elif module_type == "aws-sqs":
                self.handle_sqs_link(module, link_permissions)
            elif module_type == "aws-sns":
                self.handle_sns_link(module, link_permissions)
            else:
                raise Exception(
                    f"Unsupported module type for k8s service link: {module_type}"
                )

        iam_statements = [
            {
                "Sid": "DescribeCluster",
                "Action": ["eks:DescribeCluster"],
                "Effect": "Allow",
                "Resource": ["*"],
            }
        ]
        if self.read_buckets:
            iam_statements.append(
                AWS.prepare_read_buckets_iam_statements(self.read_buckets)
            )
        if self.write_buckets:
            iam_statements.append(
                AWS.prepare_write_buckets_iam_statements(self.write_buckets)
            )
        if self.publish_queues:
            iam_statements.append(
                AWS.prepare_publish_queues_iam_statements(self.publish_queues)
            )
        if self.subscribe_queues:
            iam_statements.append(
                AWS.prepare_subscribe_queues_iam_statements(self.subscribe_queues)
            )
        if self.publish_topics:
            iam_statements.append(
                AWS.prepare_publish_sns_iam_statements(self.publish_topics)
            )
        self.module.data["iam_policy"] = {
            "Version": "2012-10-17",
            "Statement": iam_statements,
        }
        if "image_tag" in self.layer.variables:
            self.module.data["tag"] = self.layer.variables["image_tag"]
        super(AwsK8sServiceProcessor, self).process(module_idx)

    def handle_sqs_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        # If not specified, bucket should get write permissions
        if link_permissions is None or len(link_permissions) == 0:
            link_permissions = ["publish", "subscribe"]
        for permission in link_permissions:
            if permission == "publish":
                self.publish_queues.append(
                    f"${{{{module.{linked_module.name}.queue_arn}}}}"
                )
            elif permission == "subscribe":
                self.subscribe_queues.append(
                    f"${{{{module.{linked_module.name}.queue_arn}}}}"
                )
            else:
                raise Exception(f"Invalid permission {permission}")

    def handle_sns_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        # If not specified, bucket should get write permissions
        if link_permissions is None or len(link_permissions) == 0:
            link_permissions = ["publish"]
        for permission in link_permissions:
            if permission == "publish":
                self.publish_topics.append(
                    f"${{{{module.{linked_module.name}.topic_arn}}}}"
                )
            else:
                raise Exception(f"Invalid permission {permission}")

    def handle_rds_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        for key in ["db_user", "db_name", "db_password", "db_host"]:
            self.module.data["secrets"].append(
                {
                    "name": f"{linked_module.name}_{key}",
                    "value": f"${{{{module.{linked_module.name}.{key}}}}}",
                }
            )
        if link_permissions:
            raise Exception(
                "We're not supporting IAM permissions for rds right now. "
                "Your k8s service will have the db user, name, password, "
                "and host as envars (pls see docs) and these IAM "
                "permissions are for manipulating the db itself, which "
                "I don't think is what you're looking for."
            )

    def handle_redis_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        for key in ["cache_host", "cache_auth_token"]:
            self.module.data["secrets"].append(
                {
                    "name": f"{linked_module.name}_{key}",
                    "value": f"${{{{module.{linked_module.name}.{key}}}}}",
                }
            )
        if link_permissions:
            raise Exception(
                "We're not supporting IAM permissions for redis right now. "
                "Your k8s service will have the cache's host and auth token "
                "as envars (pls see docs) and these IAM permissions "
                "are for manipulating the redis cluster itself, which "
                "I don't think is what you're looking for."
            )

    def handle_docdb_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        for key in ["db_user", "db_host", "db_password"]:
            self.module.data["secrets"].append(
                {
                    "name": f"{linked_module.name}_{key}",
                    "value": f"${{{{module.{linked_module.name}.{key}}}}}",
                }
            )
        if link_permissions:
            raise Exception(
                "We're not supporting IAM permissions for docdb right now. "
                "Your k8s service will have the db's user, password and "
                "host as envars (pls see docs) and these IAM permissions "
                "are for manipulating the docdb cluster itself, which "
                "I don't think is what you're looking for."
            )

    def handle_s3_link(
        self, linked_module: "Module", link_permissions: List[str]
    ) -> None:
        bucket_name = linked_module.data["bucket_name"]
        # If not specified, bucket should get write permissions
        if link_permissions is None or len(link_permissions) == 0:
            link_permissions = ["write"]
        for permission in link_permissions:
            if permission == "read":
                self.read_buckets.append(bucket_name)
            elif permission == "write":
                self.write_buckets.append(bucket_name)
            else:
                raise Exception(f"Invalid permission {permission}")
