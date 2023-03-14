# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Distributed synchronous data collection on a single node.

The default configuration works fine on machines equipped with 4 GPUs, but can
be scaled up or down depending on the available configuration.

The number of nodes should not be greater than the number of GPUs minus 1, as
each node will be assigned one GPU to work with, while the main worker will
keep its own GPU (presumably for model training).

"""
from argparse import ArgumentParser

import tqdm

from torchrl.collectors.collectors import (
    MultiSyncDataCollector,
    RandomPolicy,
    SyncDataCollector,
)
from torchrl.collectors.distributed import DistributedSyncDataCollector
from torchrl.envs import EnvCreator
from torchrl.envs.libs.gym import GymEnv

parser = ArgumentParser()
parser.add_argument(
    "--num_workers", default=1, type=int, help="Number of workers in each node."
)
parser.add_argument(
    "--num_nodes", default=4, type=int, help="Number of nodes for the collector."
)
parser.add_argument(
    "--frames_per_batch",
    default=800,
    type=int,
    help="Number of frames in each batch of data. Must be "
    "divisible by the product of nodes and workers.",
)
parser.add_argument(
    "--total_frames",
    default=2_000_000,
    type=int,
    help="Total number of frames collected by the collector. Must be "
    "divisible by the product of nodes and workers.",
)
parser.add_argument(
    "--backend",
    default="nccl",
    help="backend for torch.distributed. Must be one of "
    "'gloo', 'nccl' or 'mpi'. Use 'nccl' for cuda to cuda "
    "data passing.",
)
if __name__ == "__main__":
    args = parser.parse_args()
    num_workers = args.num_workers
    num_nodes = args.num_nodes
    frames_per_batch = args.frames_per_batch
    kwargs = {"backend": args.backend}
    launcher = "mp"

    device_str = "device" if num_workers <= 1 else "devices"
    if args.backend == "nccl":
        collector_kwargs = [
            {device_str: f"cuda:{i}", f"storing_{device_str}": f"cuda:{i}"}
            for i in range(1, num_nodes + 2)
        ]
    elif args.backend == "gloo":
        collector_kwargs = {device_str: "cpu", f"storing_{device_str}": "cpu"}
    else:
        raise NotImplementedError(
            f"device assignment not implemented for backend {args.backend}"
        )

    make_env = EnvCreator(lambda: GymEnv("ALE/Pong-v5"))
    action_spec = make_env().action_spec

    collector = DistributedSyncDataCollector(
        [make_env] * num_nodes,
        RandomPolicy(action_spec),
        num_workers_per_collector=num_workers,
        frames_per_batch=frames_per_batch,
        total_frames=args.total_frames,
        collector_class=SyncDataCollector
        if num_workers == 1
        else MultiSyncDataCollector,
        collector_kwargs=collector_kwargs,
        storing_device="cuda:0" if args.backend == "nccl" else "cpu",
        launcher=launcher,
        **kwargs,
    )

    pbar = tqdm.tqdm(total=collector.total_frames)
    for data in collector:
        pbar.update(data.numel())
    collector.shutdown()