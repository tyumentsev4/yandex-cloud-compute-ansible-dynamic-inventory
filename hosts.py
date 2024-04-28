#!/usr/bin/env python3
import argparse
import json
import os
import sys
from dataclasses import dataclass

from yandexcloud import SDK
from yandex.cloud.compute.v1.instance_service_pb2 import ListInstancesRequest
from yandex.cloud.compute.v1.instance_service_pb2_grpc import InstanceServiceStub
from yandex.cloud.compute.v1.zone_service_pb2 import ListZonesRequest
from yandex.cloud.compute.v1.zone_service_pb2_grpc import ZoneServiceStub


@dataclass
class Host:
    name: str
    zone: str
    fqdn: str
    labels: dict
    ip_address: str


class Inventory:
    def __init__(self, groups: list[str]):
        self._groups = {"all": {"children": []}, "_meta": {"hostvars": {}}}
        for group in groups:
            self._create_group(group_name=group.replace("-", "_"))
        self._hosts = dict()

    def __str__(self) -> str:
        return json.dumps(self._groups)

    def get_host_info(self, host_name: str) -> str:
        return json.dumps(self._hosts.get(host_name))

    def add_host_to_inventory(self, host: Host) -> None:
        host_name = host.name
        self._add_host_to_group(host)
        self._hosts[host_name] = {"ansible_host": host.ip_address}
        for key, value in self._hosts[host_name].items():
            self._add_host_info_to_meta(host_name, key, value)

    def _add_host_to_group(self, host: Host) -> None:
        self._groups[host.zone]["hosts"].append(host.name)
        group_name = host.labels.get("ansible_group")
        if group_name is not None:
            self._create_group(group_name)
            self._groups[group_name]["hosts"].append(host.name)

    def _create_group(self, group_name):
        if group_name not in self._groups:
            self._groups[group_name] = {"hosts": []}
            self._groups["all"]["children"].append(group_name)

    def _add_host_info_to_meta(self, host_name, key, value) -> None:
        if host_name not in self._groups["_meta"]["hostvars"]:
            self._groups["_meta"]["hostvars"][host_name] = {}
        self._groups["_meta"]["hostvars"][host_name][key] = value


class YandexCloudProvider:
    def __init__(self):
        self.iam_token = (
            os.getenv("TF_VAR_yc_iam_token")
            if os.getenv("TF_VAR_yc_iam_token")
            else os.getenv("YC_TOKEN")
        )
        self.folder_id = (
            os.getenv("TF_VAR_yc_folder_id")
            if os.getenv("TF_VAR_yc_folder_id")
            else os.getenv("YC_FOLDER_ID")
        )
        if self.iam_token is None:
            print("Please set TF_VAR_yc_iam_token variable. `export TF_VAR_yc_iam_token=$(yc iam create-token)`")
            sys.exit(1)
        if self.folder_id is None:
            print("Please set TF_VAR_yc_folder_id variable. `export TF_VAR_yc_folder_id=$(yc config get folder-id)`")
            sys.exit(1)
        self.yandex_sdk = SDK(iam_token=self.iam_token)

    def _get_instances(self) -> list:
        return (
            self.yandex_sdk.client(InstanceServiceStub)
            .List(ListInstancesRequest(folder_id=self.folder_id))
            .instances
        )

    def get_availability_zone_ids(self) -> list[str]:
        return [
            zone.id
            for zone in self.yandex_sdk.client(ZoneServiceStub)
            .List(ListZonesRequest())
            .zones
        ]

    @staticmethod
    def _instance_to_host(instance) -> Host:
        return Host(
            name=instance.name.replace("-", "_"),
            fqdn=instance.fqdn,
            ip_address=instance.network_interfaces[
                0
            ].primary_v4_address.one_to_one_nat.address,
            labels={key: value.replace("-", "_") for key, value in instance.labels.items()},
            zone=instance.zone_id.replace("-", "_"),
        )

    def get_hosts(self) -> list[Host]:
        return list(map(self._instance_to_host, self._get_instances()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    host_or_list = parser.add_mutually_exclusive_group(required=True)
    host_or_list.add_argument(
        "--list",
        action="store_true",
        help="output to stdout a JSON object that contains all the groups to be managed",
    )
    host_or_list.add_argument(
        "--host",
        type=str,
        action="store",
        help="output to stdout a JSON object, either empty or containing variables",
    )
    return parser.parse_args()


def main():
    yandex_cloud_provider = YandexCloudProvider()
    args = parse_args()
    inventory = Inventory(groups=yandex_cloud_provider.get_availability_zone_ids())
    for host in yandex_cloud_provider.get_hosts():
        inventory.add_host_to_inventory(host)
    if args.list:
        print(inventory)
    else:
        print(inventory.get_host_info(args.host))


if __name__ == "__main__":
    main()
